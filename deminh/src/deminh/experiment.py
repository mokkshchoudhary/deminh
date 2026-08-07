"""The controlled three-arm experiment.

Design decision worth defending in the methodology chapter
----------------------------------------------------------
Generation is run ONCE per question, then deep-copied into the three arms. Each
copy receives the *identical* injected error, and only then does the arm-specific
verifier run.

Two reasons:

  1. Confound removal. If you re-generated per arm, the arms would see different
     extractions and different analyst plans, and any difference in outcome could
     be generation variance rather than verifier quality. Sharing one generation
     pass makes the verifier the only thing that varies — which is what your
     research question requires.

  2. Compute. An 8B model at 4-bit on your hardware is the bottleneck. One
     generation pass instead of three cuts the dominant cost by roughly a third
     of itself, and makes a larger test set feasible within the timetable.

The cost is that you cannot measure whether verification changes generation
behaviour downstream. It does not, in this architecture — verification runs after
the Analyst and before the Writer, and the Writer is given the verified value
either way — but say so explicitly rather than leaving it to be noticed.

Caveat: the self-check arm still calls the model, so that arm is not free.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .graph import Configuration, Pipeline
from .injection import ErrorCategory, InjectionConfig, InjectionHarness
from .llm import LLMBackend
from .metrics import (
    detection_by_category,
    detection_by_mechanism,
    detection_metrics,
    mcnemar,
    mitigation_metrics,
    was_corrupted,
    was_flagged,
)
from .schemas import PipelineRecord

log = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    injection: InjectionConfig
    arms: list[Configuration] = field(default_factory=lambda: list(Configuration))
    use_langgraph: bool = True
    balanced_categories: bool = True   # cycle categories instead of sampling
    output_dir: str = "results"


class Experiment:
    def __init__(self, backend: LLMBackend, config: ExperimentConfig):
        self.backend = backend
        self.config = config
        self.harness = InjectionHarness(config.injection)
        self.pipelines = {
            arm: Pipeline(backend, arm) for arm in config.arms
        }

    # -- running -----------------------------------------------------------

    def run(self, records: list[PipelineRecord]) -> dict[Configuration, list[PipelineRecord]]:
        results: dict[Configuration, list[PipelineRecord]] = {a: [] for a in self.config.arms}
        categories = self.config.injection.categories

        total = len(records)
        for index, record in enumerate(records):
            generated = self._generate_once(record)
            if generated is None:
                log.warning("Skipping %s: generation produced no claim.", record.question_id)
                log.info("Progress: %d/%d records generated (%s skipped).",
                         index + 1, total, record.question_id)
                continue

            log.info("Progress: %d/%d records generated (%s ok).",
                     index + 1, total, record.question_id)

            for arm in self.config.arms:
                arm_record = copy.deepcopy(generated)

                if self.config.balanced_categories:
                    # Deterministic round-robin: every arm gets the same category
                    # for the same question, and categories are evenly represented.
                    if index % 2 == 0:
                        self.harness.corrupt_with(
                            arm_record, categories[(index // 2) % len(categories)]
                        )
                else:
                    self.harness.maybe_corrupt(arm_record)

                arm_record.meta["pre_verification_answer"] = (
                    arm_record.claims[0].value if arm_record.claims else None
                )
                arm_record.meta["arm"] = arm.value

                pipeline = self.pipelines[arm]
                if pipeline.verifier is not None:
                    pipeline.node_verify({"record": arm_record})
                pipeline.node_write({"record": arm_record})

                results[arm].append(arm_record)

        return results

    def _generate_once(self, record: PipelineRecord) -> Optional[PipelineRecord]:
        """Extraction and analysis, shared by every arm."""
        seed_pipeline = self.pipelines[self.config.arms[0]]
        working = copy.deepcopy(record)
        state = {"record": working}
        state.update(seed_pipeline.node_extract(state))
        state.update(seed_pipeline.node_analyse(state))
        working = state["record"]
        return working if working.claims else None

    # -- reporting ---------------------------------------------------------

    def summarise(self, results: dict[Configuration, list[PipelineRecord]]) -> dict:
        summary: dict = {"arms": {}, "comparisons": {}}

        for arm, records in results.items():
            summary["arms"][arm.value] = {
                "n_records": len(records),
                "n_corrupted": sum(1 for r in records if was_corrupted(r)),
                "detection": detection_metrics(records).as_dict(),
                "detection_by_category": detection_by_category(records),
                "flags_by_mechanism": detection_by_mechanism(records),
                "mitigation": mitigation_metrics(records).as_dict(),
                "mean_coverage": round(
                    sum(r.report.coverage() for r in records if r.report)
                    / max(sum(1 for r in records if r.report), 1), 4
                ),
            }

        # The headline comparison: does independent checking detect more than
        # the model checking itself, on the same items?
        if Configuration.SELF_CHECK in results and Configuration.DEMINH in results:
            self_records = results[Configuration.SELF_CHECK]
            deminh_records = results[Configuration.DEMINH]
            paired = self._align(self_records, deminh_records)

            correct_self = [was_flagged(a) == was_corrupted(a) for a, _ in paired]
            correct_deminh = [was_flagged(b) == was_corrupted(b) for _, b in paired]
            test = mcnemar(correct_deminh, correct_self)

            summary["comparisons"]["deminh_vs_self_check"] = {
                "n_paired": len(paired),
                "deminh_right_self_wrong": test.b,
                "self_right_deminh_wrong": test.c,
                "n_discordant": test.n_discordant,
                "chi2": round(test.statistic, 4),
                "p_value": round(test.p_value, 6),
                "note": (
                    "Fewer than ~25 discordant pairs makes this approximation "
                    "unreliable; report n_discordant alongside p."
                ),
            }
        return summary

    @staticmethod
    def _align(a: list[PipelineRecord],
               b: list[PipelineRecord]) -> list[tuple[PipelineRecord, PipelineRecord]]:
        index_b = {r.question_id: r for r in b}
        return [(r, index_b[r.question_id]) for r in a if r.question_id in index_b]

    def save(self, results: dict[Configuration, list[PipelineRecord]],
             summary: dict) -> Path:
        out = Path(self.config.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        for arm, records in results.items():
            rows = [{
                "question_id": r.question_id,
                "question": r.question,
                "gold_answer": r.gold_answer,
                "pre_verification_answer": r.meta.get("pre_verification_answer"),
                "final_answer": r.final_answer,
                "injected": [asdict(i) for i in r.injected],
                "flags": [
                    {"claim_id": f.claim_id, "mechanism": f.mechanism.value,
                     "message": f.message, "proposed_value": f.proposed_value}
                    for f in (r.report.flags if r.report else [])
                ],
                "coverage": r.report.coverage() if r.report else None,
            } for r in records]
            (out / f"records_{arm.value}.json").write_text(
                json.dumps(rows, indent=2), encoding="utf-8"
            )

        return out
