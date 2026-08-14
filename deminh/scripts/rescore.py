#!/usr/bin/env python3
"""Re-score detection against answer-correctness instead of injection status.

Why this script exists
----------------------
`metrics.detection_metrics` defines a positive as "an error was injected into
this record". That is the right definition for measuring whether a verifier
catches the *corpus's* planted errors, and it is what `summary.json` reports.

It is the wrong definition for asking whether a flag was *justified*. Base
accuracy on FinQA under this pipeline is ~0.32, so roughly two thirds of the
un-injected records already carry a naturally wrong answer. A verifier that
flags one of those is counted as a false positive under the injection
definition while being, in fact, correct. run_002's deminh arm shows the size
of the distortion: 59% of its "false positives" are flagging genuinely wrong
answers (see ANALYSIS_REPAIR_POLICY_AND_FPR.md).

So this script scores every record twice:

  (1) INJECTION-BASED   positive = an error was injected (the current headline
                        definition; reproduces summary.json exactly).
  (2) CORRECTNESS-BASED positive = the final answer is actually wrong against
                        gold_answer.

Both use the same predicted label - "did any mechanism raise a flag" - so the
two tables differ only in ground truth, and the arms stay comparable to each
other under either definition.

Neither table replaces the other. Report both: (1) is the pre-registered
measure against a known-corruption corpus; (2) is what the flag is worth in
practice. Injected errors are a proxy for natural ones, and (2) is the closest
thing in the current data to a measurement on natural errors.

Matching against gold reuses `metrics._percent_aware_match` - the *same*
function and the same rel_tol=1e-2 the mitigation scorer uses - rather than a
reimplementation, so a correctness call here can never disagree with a
correctness call in `mitigation_metrics`. FinQA stores percentage answers
inconsistently as fractions or whole percents, which is what that function
absorbs.

No model is called. This runs entirely off the committed record dumps, so it
can be re-run on any past or future run dir at no compute cost.

Usage
-----
    python scripts/rescore.py results/run_002
    python scripts/rescore.py results/run_001 results/run_002 results/run_003a
    python scripts/rescore.py results/run_00* --json results/rescore.json

Multiple run dirs are scored individually and then pooled. Pooling is only
valid for runs sharing pinned decoding, identical prompts and taxonomy, and
covering disjoint dataset slices - which is the condition run_001, run_002 and
run_003a/b were constructed to satisfy.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deminh.metrics import ConfusionMatrix, _percent_aware_match

# Arm order is fixed for reporting: floor, cheap baseline, proposal.
ARMS = ("no_verifier", "self_check", "deminh")


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def answer_is_correct(value: Optional[float], gold: Optional[float],
                      question: Optional[str], rel_tol: float) -> bool:
    """Is `value` the right answer to `question`, given gold?

    A missing answer counts as wrong, not as unknown. `_percent_aware_match`
    would raise on a None value for a percentage question (it multiplies by
    100 before testing), so the guard has to sit here rather than be assumed.
    """
    if value is None or gold is None:
        return False
    return _percent_aware_match(float(value), float(gold), question or "", rel_tol)


def _tally(matrix: ConfusionMatrix, actual: bool, predicted: bool) -> None:
    if actual and predicted:
        matrix.tp += 1
    elif actual and not predicted:
        matrix.fn += 1
    elif not actual and predicted:
        matrix.fp += 1
    else:
        matrix.tn += 1


@dataclass
class ArmScore:
    """One arm's confusion matrices under both ground-truth definitions."""
    injection: ConfusionMatrix
    correctness: ConfusionMatrix
    n_records: int
    n_no_gold: int          # excluded from the correctness matrix only
    n_in_scope: int = 0     # records the correctness scope admitted

    @property
    def n_scored_correctness(self) -> int:
        return self.n_in_scope - self.n_no_gold


def score_records(rows: list[dict], rel_tol: float = 1e-2,
                  answer_field: str = "final_answer",
                  scope: str = "all") -> ArmScore:
    """Score one arm's saved records under both definitions.

    `rows` are the dicts written by `experiment.Experiment.save`.

    The predicted label is `bool(row["flags"])`. That matches
    `metrics.was_flagged`, which counts a record as flagged when any flag has
    severity ERROR - and every flag every mechanism emits is ERROR (no WARN or
    INFO is constructed anywhere in the codebase), which is why the saved rows
    can omit severity without changing the result.

    Two choices govern the correctness label, and they change the answer
    materially, so both are explicit parameters rather than buried defaults.

    `answer_field`
        "final_answer" (default) scores the answer the pipeline actually
        delivers, after any repair. A wrong answer that was flagged and then
        successfully repaired then counts as correct-and-flagged, i.e. a false
        positive. That is the conservative reading: a verifier cannot claim
        credit twice, once for detecting and again for having fixed what it
        detected.

        "pre_verification_answer" scores the answer the verifier was actually
        looking at when it decided whether to flag. That isolates the
        *detection* decision from repair quality, which is arguably the fairer
        question to ask of a detector, and it is what run_002's analysis note
        used. On the deminh arm the two differ by 8 records (25 repairs, of
        which 8 land in the clean subpopulation), which is enough to move
        precision by ~5 points - hence: state which one a reported figure used.

    `scope`
        "all" (default) scores every record.
        "clean" scores only the non-injected records - the natural-error
        subpopulation. This is the population that answers "when the verifier
        fires on a record we did not sabotage, is it right to?", and it is the
        closest thing in the current data to a measurement on natural rather
        than injected errors. Note it is NOT comparable to the injection-based
        precision, which is computed over all records: quoting one against the
        other compares two different populations.
    """
    if scope not in ("all", "clean"):
        raise ValueError(f"scope must be 'all' or 'clean', got {scope!r}")

    injection = ConfusionMatrix()
    correctness = ConfusionMatrix()
    n_no_gold = 0
    n_scoped = 0

    for row in rows:
        flagged = bool(row.get("flags"))
        injected = bool(row.get("injected"))

        # (1) injection-based: positive = an error was injected.
        # Always over all records - restricting this to clean records would
        # leave no positives at all.
        _tally(injection, injected, flagged)

        # (2) correctness-based: positive = the answer is wrong
        if scope == "clean" and injected:
            continue
        n_scoped += 1

        gold = row.get("gold_answer")
        if gold is None:
            n_no_gold += 1
            continue
        wrong = not answer_is_correct(
            row.get(answer_field), gold, row.get("question"), rel_tol
        )
        _tally(correctness, wrong, flagged)

    return ArmScore(injection=injection, correctness=correctness,
                    n_records=len(rows), n_no_gold=n_no_gold,
                    n_in_scope=n_scoped)


def add_matrices(a: ConfusionMatrix, b: ConfusionMatrix) -> ConfusionMatrix:
    """Pool two confusion matrices.

    Summing cells is the correct way to pool across disjoint slices; averaging
    the per-run precision figures is not, because the runs have different
    positive counts.
    """
    return ConfusionMatrix(tp=a.tp + b.tp, fp=a.fp + b.fp,
                           fn=a.fn + b.fn, tn=a.tn + b.tn)


def pool(scores: list[ArmScore]) -> ArmScore:
    total = ArmScore(ConfusionMatrix(), ConfusionMatrix(), 0, 0, 0)
    for score in scores:
        total.injection = add_matrices(total.injection, score.injection)
        total.correctness = add_matrices(total.correctness, score.correctness)
        total.n_records += score.n_records
        total.n_no_gold += score.n_no_gold
        total.n_in_scope += score.n_in_scope
    return total


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_run(run_dir: Path) -> dict[str, list[dict]]:
    """Load every arm's records from one run dir. Missing arms are skipped."""
    arms: dict[str, list[dict]] = {}
    for arm in ARMS:
        path = run_dir / f"records_{arm}.json"
        if path.exists():
            arms[arm] = json.loads(path.read_text(encoding="utf-8"))
    if not arms:
        raise SystemExit(f"No records_*.json found in {run_dir}")
    return arms


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

HEADER = (f"{'arm':<13}{'ground truth':<15}{'TP':>5}{'FP':>5}{'FN':>5}{'TN':>5}"
          f"{'prec':>8}{'recall':>8}{'F1':>8}{'FPR':>8}")


def _row(arm: str, label: str, m: ConfusionMatrix) -> str:
    return (f"{arm:<13}{label:<15}{m.tp:>5}{m.fp:>5}{m.fn:>5}{m.tn:>5}"
            f"{m.precision:>8.4f}{m.recall:>8.4f}{m.f1:>8.4f}"
            f"{m.false_positive_rate:>8.4f}")


def print_table(title: str, scores: dict[str, ArmScore]) -> None:
    print()
    print(title)
    print("-" * len(HEADER))
    print(HEADER)
    print("-" * len(HEADER))
    for arm in ARMS:
        if arm not in scores:
            continue
        score = scores[arm]
        print(_row(arm, "injection", score.injection))
        print(_row(arm, "correctness", score.correctness))
        print("-" * len(HEADER))

    excluded = {arm: s.n_no_gold for arm, s in scores.items() if s.n_no_gold}
    any_score = next(iter(scores.values()))
    print(f"n_records per arm: {any_score.n_records}   "
          f"in correctness scope: {any_score.n_in_scope}")
    if excluded:
        detail = ", ".join(f"{arm}: {n}" for arm, n in excluded.items())
        print(f"excluded from correctness-based scoring (no gold_answer): {detail}")
    else:
        print("excluded from correctness-based scoring (no gold_answer): 0")


def print_sensitivity(run_dirs: dict[str, dict[str, list[dict]]],
                      rel_tol: float) -> None:
    """Show the correctness metric under all four definition choices.

    The scope x answer_field grid is not a footnote: on run_002's deminh arm it
    moves precision from 0.54 to 0.67. Printing it makes the reported figure a
    stated choice rather than an accident, which is the difference between a
    defensible number and one an examiner can pull apart.
    """
    print()
    print("=== correctness-metric sensitivity to definition (pooled over all run dirs) ===")
    head = (f"{'arm':<13}{'scope':<7}{'answer':<10}{'TP':>5}{'FP':>5}{'FN':>5}{'TN':>5}"
            f"{'prec':>8}{'recall':>8}{'F1':>8}{'FPR':>8}")
    print("-" * len(head))
    print(head)
    print("-" * len(head))
    for arm in ARMS:
        for scope in ("all", "clean"):
            for field, label in (("final_answer", "final"),
                                 ("pre_verification_answer", "pre")):
                collected = [
                    score_records(rows[arm], rel_tol=rel_tol,
                                  answer_field=field, scope=scope)
                    for rows in run_dirs.values() if arm in rows
                ]
                if not collected:
                    continue
                m = pool(collected).correctness
                print(f"{arm:<13}{scope:<7}{label:<10}{m.tp:>5}{m.fp:>5}{m.fn:>5}{m.tn:>5}"
                      f"{m.precision:>8.4f}{m.recall:>8.4f}{m.f1:>8.4f}"
                      f"{m.false_positive_rate:>8.4f}")
        print("-" * len(head))


def as_dict(score: ArmScore) -> dict:
    return {
        "n_records": score.n_records,
        "n_in_correctness_scope": score.n_in_scope,
        "n_excluded_no_gold": score.n_no_gold,
        "n_scored_correctness": score.n_scored_correctness,
        "injection_based": score.injection.as_dict(),
        "correctness_based": score.correctness.as_dict(),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+",
                        help="One or more results/<run> directories to score.")
    parser.add_argument("--rel-tol", type=float, default=1e-2,
                        help="Relative tolerance for the gold-answer match. "
                             "Default 1e-2, matching mitigation_metrics.")
    parser.add_argument("--answer", choices=["final", "pre"], default="final",
                        help="Which answer the correctness label scores: 'final' "
                             "(post-repair, what the pipeline delivers; default) "
                             "or 'pre' (what the verifier saw when it decided).")
    parser.add_argument("--scope", choices=["all", "clean"], default="all",
                        help="Which records the correctness label covers: 'all' "
                             "(default) or 'clean' (non-injected only - the "
                             "natural-error subpopulation).")
    parser.add_argument("--sensitivity", action="store_true",
                        help="Also print the correctness metric under all four "
                             "scope x answer combinations.")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Also write the full result as JSON to this path.")
    args = parser.parse_args()

    answer_field = ("final_answer" if args.answer == "final"
                    else "pre_verification_answer")

    per_run: dict[str, dict[str, ArmScore]] = {}
    raw_rows: dict[str, dict[str, list[dict]]] = {}

    for raw in args.run_dirs:
        run_dir = Path(raw)
        if not run_dir.is_dir():
            raise SystemExit(f"Not a directory: {run_dir}")
        arms = load_run(run_dir)
        raw_rows[run_dir.name] = arms
        per_run[run_dir.name] = {
            arm: score_records(rows, rel_tol=args.rel_tol,
                               answer_field=answer_field, scope=args.scope)
            for arm, rows in arms.items()
        }

    print(f"correctness definition: scope={args.scope}  answer={answer_field}  "
          f"rel_tol={args.rel_tol}")

    for name, scores in per_run.items():
        print_table(f"=== {name} ===", scores)

    pooled: dict[str, ArmScore] = {}
    if len(per_run) > 1:
        for arm in ARMS:
            collected = [s[arm] for s in per_run.values() if arm in s]
            if collected:
                pooled[arm] = pool(collected)
        print_table(f"=== POOLED ({', '.join(per_run)}) ===", pooled)

    if args.sensitivity:
        print_sensitivity(raw_rows, args.rel_tol)

    if args.json_out:
        payload = {
            "rel_tol": args.rel_tol,
            "scope": args.scope,
            "answer_field": answer_field,
            "runs": {name: {arm: as_dict(s) for arm, s in scores.items()}
                     for name, scores in per_run.items()},
        }
        if pooled:
            payload["pooled"] = {arm: as_dict(s) for arm, s in pooled.items()}
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWritten to {Path(args.json_out).resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
