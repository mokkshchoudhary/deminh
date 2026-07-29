"""End-to-end tests of the three configurations, using a scripted backend.

These exercise the wiring, not the model. They are the tests that catch the
errors that waste the most time: an arm that silently never runs its verifier, a
repair that never reaches the final answer, an injection that no arm can see.
Run them before every experiment run.
"""

from __future__ import annotations

import json
import re

import pytest

from deminh.data import synthetic_records
from deminh.graph import Configuration, Pipeline
from deminh.injection import ErrorCategory, InjectionConfig, InjectionHarness
from deminh.llm import GenerationConfig, LLMBackend


class ScriptedBackend(LLMBackend):
    """A backend that behaves like a competent model on the synthetic records.

    It reads the figures out of the prompt rather than inventing them, so the
    pipeline produces a genuinely correct answer and any wrongness in the test
    outcome comes from injection, not from a sloppy stub.
    """

    name = "scripted"

    def __init__(self, self_check_verdict: str = "correct"):
        self.self_check_verdict = self_check_verdict
        self.calls: list[str] = []

    def chat(self, system: str, user: str, config: GenerationConfig | None = None) -> str:
        if "You extract financial figures" in system:
            self.calls.append("extract")
            return json.dumps({"figures": self._figures(user)})
        if "You plan the arithmetic" in system:
            self.calls.append("analyse")
            return json.dumps(self._plan(user))
        if "checking whether a numeric answer is correct" in system:
            self.calls.append("selfcheck")
            return json.dumps({"verdict": self.self_check_verdict,
                               "reason": "scripted", "corrected_value": None})
        self.calls.append("write")
        return "The answer is stated above."

    @staticmethod
    def _figures(user: str) -> list[dict]:
        figures = []
        for line in user.splitlines():
            match = re.match(r"^([A-Za-z ]+) \| ([\d,]+)$", line.strip())
            if match:
                label, value = match.group(1).strip(), match.group(2)
                figures.append({
                    "label": label.lower(),
                    "value": float(value.replace(",", "")),
                    "scale": 1,
                    "unit": "USD",
                    "location": "table_1",
                    "source_text": f"{label} | {value}",
                })
        return figures

    @staticmethod
    def _plan(user: str) -> dict:
        ids = dict(re.findall(r"- (fig_\w+): ([a-z ]+) =", user))
        by_label = {label.strip(): fid for fid, label in ids.items()}
        gross = by_label.get("gross profit")
        revenue = by_label.get("revenue")
        if not (gross and revenue):
            return {"expression": "0", "bindings": {}, "estimated_result": 0.0}

        values = dict(re.findall(r"- (fig_\w+): [a-z ]+ = ([\d.]+)", user))
        result = float(values[gross]) / float(values[revenue]) * 100
        return {
            "expression": "(gross / revenue) * 100",
            "bindings": {"gross": gross, "revenue": revenue},
            "operation_label": "gross profit margin",
            "estimated_result": round(result, 4),
            "unit": "percent",
        }


@pytest.fixture
def record():
    return synthetic_records(n=1, seed=5)[0]


def test_clean_pipeline_gets_the_right_answer(record):
    pipeline = Pipeline(ScriptedBackend(), Configuration.DEMINH)
    result = pipeline.run_sequential(record)
    assert result.final_answer == pytest.approx(record.gold_answer, rel=1e-3)


def test_no_verifier_arm_never_flags(record):
    pipeline = Pipeline(ScriptedBackend(), Configuration.NO_VERIFIER)
    result = pipeline.run_sequential(record)
    assert pipeline.verifier is None
    assert result.report is None


def test_deminh_detects_and_repairs_an_arithmetic_slip(record):
    pipeline = Pipeline(ScriptedBackend(), Configuration.DEMINH)
    state = {"record": record}
    state.update(pipeline.node_extract(state))
    state.update(pipeline.node_analyse(state))

    harness = InjectionHarness(InjectionConfig(categories=[ErrorCategory.ARITHMETIC_SLIP],
                                               seed=2))
    harness.corrupt_with(state["record"], ErrorCategory.ARITHMETIC_SLIP)

    state.update(pipeline.node_verify(state))
    state.update(pipeline.node_write(state))

    result = state["record"]
    assert result.report.flagged_claim_ids, "arithmetic slip went undetected"
    assert result.final_answer == pytest.approx(record.gold_answer, rel=1e-3), \
        "recomputation should have restored the correct value"


def test_deminh_detects_an_invented_figure(record):
    pipeline = Pipeline(ScriptedBackend(), Configuration.DEMINH)
    state = {"record": record}
    state.update(pipeline.node_extract(state))
    state.update(pipeline.node_analyse(state))

    harness = InjectionHarness(InjectionConfig(categories=[ErrorCategory.INVENTED_FIGURE],
                                               seed=3))
    harness.corrupt_with(state["record"], ErrorCategory.INVENTED_FIGURE)
    state.update(pipeline.node_verify(state))

    flags = state["record"].report.flags
    assert any(f.mechanism.value == "provenance" for f in flags)


def test_self_check_arm_calls_the_model(record):
    backend = ScriptedBackend(self_check_verdict="incorrect")
    pipeline = Pipeline(backend, Configuration.SELF_CHECK)
    state = {"record": record}
    state.update(pipeline.node_extract(state))
    state.update(pipeline.node_analyse(state))
    state.update(pipeline.node_verify(state))

    assert "selfcheck" in backend.calls
    assert state["record"].report.flagged_claim_ids


def test_deterministic_arm_makes_no_model_calls_during_verification(record):
    """The independence claim, asserted as a test.

    If this ever fails, the DeMiNH arm has acquired a model dependency and the
    central methodological claim of the dissertation is no longer true of the
    code. Keep this test.
    """
    backend = ScriptedBackend()
    pipeline = Pipeline(backend, Configuration.DEMINH)
    state = {"record": record}
    state.update(pipeline.node_extract(state))
    state.update(pipeline.node_analyse(state))

    before = list(backend.calls)
    state.update(pipeline.node_verify(state))
    assert backend.calls == before, "verification must not consult the model"


def test_full_experiment_produces_a_summary(tmp_path):
    """Smoke test of the whole three-arm loop, including the summary tables."""
    from deminh.experiment import Experiment, ExperimentConfig

    experiment = Experiment(
        backend=ScriptedBackend(),
        config=ExperimentConfig(
            injection=InjectionConfig(categories=list(ErrorCategory), rate=1.0, seed=11),
            arms=list(Configuration),
            output_dir=str(tmp_path),
        ),
    )
    results = experiment.run(synthetic_records(n=12, seed=8))
    summary = experiment.summarise(results)

    assert set(summary["arms"]) == {c.value for c in Configuration}
    for arm in summary["arms"].values():
        assert arm["n_records"] == 12
        assert "detection" in arm and "mitigation" in arm

    # The no-verifier arm must never detect anything, by construction.
    assert summary["arms"]["no_verifier"]["detection"]["tp"] == 0
    # The deterministic arm must catch at least the arithmetic slips.
    assert summary["arms"]["deminh"]["detection"]["tp"] > 0

    path = experiment.save(results, summary)
    assert (path / "summary.json").exists()
