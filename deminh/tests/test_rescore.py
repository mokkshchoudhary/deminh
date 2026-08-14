"""Tests for the correctness-based re-scoring tool.

These matter more than they look. `rescore.py` produces a number that is meant
to sit next to the headline detection result in the dissertation, and it is
computed off saved JSON with no model in the loop - so nothing else would catch
a transposed confusion cell or a silently-dropped record. The regression test
against run_002's published decomposition is the load-bearing one: it pins the
tool to numbers that were derived independently, by hand, in
ANALYSIS_REPAIR_POLICY_AND_FPR.md.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# rescore.py lives in scripts/, which is not an importable package, so load it
# by path rather than restructuring the repo for the sake of a test. The
# sys.modules registration is required, not tidiness: @dataclass resolves its
# field types via sys.modules[cls.__module__], which is None for a module that
# was created but never registered.
_SPEC = importlib.util.spec_from_file_location(
    "rescore", Path(__file__).resolve().parents[1] / "scripts" / "rescore.py"
)
rescore = importlib.util.module_from_spec(_SPEC)
sys.modules["rescore"] = rescore
_SPEC.loader.exec_module(rescore)


def row(qid="q1", *, injected=False, flagged=False, gold=10.0,
        final=10.0, pre=None, question="what is the value?"):
    """One saved record, shaped exactly as Experiment.save writes it."""
    return {
        "question_id": qid,
        "question": question,
        "gold_answer": gold,
        "pre_verification_answer": final if pre is None else pre,
        "final_answer": final,
        "injected": [{"category": "arithmetic_slip"}] if injected else [],
        "flags": [{"claim_id": "c1", "mechanism": "recompute",
                   "message": "m", "proposed_value": None}] if flagged else [],
        "coverage": 0.0,
    }


# --------------------------------------------------------------------------
# The two ground-truth definitions
# --------------------------------------------------------------------------

def test_injection_and_correctness_disagree_on_the_same_record():
    """The whole point of the tool: a record that is clean but wrong.

    Not injected, so the injection definition calls a flag a false positive.
    Answer is wrong, so the correctness definition calls the same flag a true
    positive. If these two ever agree on this record the tool is not doing
    anything.
    """
    score = rescore.score_records([row(injected=False, flagged=True,
                                       gold=10.0, final=999.0)])
    assert (score.injection.fp, score.injection.tp) == (1, 0)
    assert (score.correctness.tp, score.correctness.fp) == (1, 0)


@pytest.mark.parametrize("flagged,wrong,cell", [
    (True, True, "tp"),
    (True, False, "fp"),
    (False, True, "fn"),
    (False, False, "tn"),
])
def test_correctness_confusion_cells(flagged, wrong, cell):
    final = 999.0 if wrong else 10.0
    score = rescore.score_records([row(flagged=flagged, gold=10.0, final=final)])
    assert getattr(score.correctness, cell) == 1
    assert sum([score.correctness.tp, score.correctness.fp,
                score.correctness.fn, score.correctness.tn]) == 1


def test_injection_matrix_is_unaffected_by_scope_and_answer_field():
    """Definition (1) must stay identical to summary.json under every option."""
    rows = [row("a", injected=True, flagged=True),
            row("b", injected=False, flagged=True, final=999.0)]
    base = rescore.score_records(rows).injection.as_dict()
    for scope in ("all", "clean"):
        for field in ("final_answer", "pre_verification_answer"):
            other = rescore.score_records(rows, scope=scope, answer_field=field)
            assert other.injection.as_dict() == base


# --------------------------------------------------------------------------
# Exclusions and options
# --------------------------------------------------------------------------

def test_records_without_gold_are_excluded_from_correctness_only():
    rows = [row("a", gold=None, flagged=True), row("b", gold=10.0, final=10.0)]
    score = rescore.score_records(rows)
    assert score.n_no_gold == 1
    assert score.n_scored_correctness == 1
    # still counted on the injection side, which needs no gold answer
    assert (score.injection.fp + score.injection.tn) == 2


def test_missing_final_answer_counts_as_wrong_not_as_skipped():
    """A None answer is a wrong answer, not an unknown one.

    It also must not raise: _percent_aware_match multiplies by 100 for
    percentage questions and would blow up on None.
    """
    score = rescore.score_records([row(flagged=True, gold=10.0, final=None,
                                       question="what percent grew?")])
    assert score.correctness.tp == 1
    assert score.n_no_gold == 0


def test_scope_clean_drops_injected_records_from_correctness():
    rows = [row("a", injected=True, flagged=True, final=999.0),
            row("b", injected=False, flagged=True, final=999.0)]
    score = rescore.score_records(rows, scope="clean")
    assert score.n_in_scope == 1
    assert score.correctness.tp == 1          # only the clean record
    assert score.injection.tp == 1            # injection side still sees both
    assert score.injection.fp == 1


def test_answer_field_selects_pre_verification_value():
    """A repair that fixed the answer flips the record between the two fields."""
    r = row(flagged=True, gold=10.0, pre=999.0, final=10.0)
    assert rescore.score_records([r]).correctness.fp == 1
    assert rescore.score_records(
        [r], answer_field="pre_verification_answer").correctness.tp == 1


def test_percent_aware_matching_is_used():
    """Reuses mitigation_metrics' matcher, so a x100 flip must be tolerated."""
    r = row(gold=24.69, final=0.2469, question="what percent of total?")
    assert rescore.score_records([r]).correctness.tn == 1


def test_scope_rejects_unknown_value():
    with pytest.raises(ValueError):
        rescore.score_records([row()], scope="nonsense")


# --------------------------------------------------------------------------
# Pooling
# --------------------------------------------------------------------------

def test_pooling_sums_cells_rather_than_averaging_rates():
    """Two runs with very different positive counts.

    Averaging the per-run precisions would give 0.75; summing cells - the
    correct pooling for disjoint slices - gives 0.9.
    """
    a = rescore.score_records([row(f"a{i}", flagged=True, final=999.0)
                               for i in range(9)]
                              + [row("a9", flagged=True, final=10.0)])
    b = rescore.score_records([row("b0", flagged=True, final=10.0)])
    pooled = rescore.pool([a, b])
    assert (pooled.correctness.tp, pooled.correctness.fp) == (9, 2)
    assert pooled.n_records == 11
    assert a.correctness.precision == pytest.approx(0.9)
    assert b.correctness.precision == pytest.approx(0.0)
    assert pooled.correctness.precision == pytest.approx(9 / 11)


# --------------------------------------------------------------------------
# Regression against the published run_002 analysis
# --------------------------------------------------------------------------

RUN_002 = Path(__file__).resolve().parents[1] / "results" / "run_002"


@pytest.mark.skipif(not RUN_002.exists(), reason="run_002 results not present")
def test_reproduces_run_002_injection_metrics_from_summary_json():
    """Definition (1) must reproduce the committed summary.json exactly."""
    summary = json.loads((RUN_002 / "summary.json").read_text(encoding="utf-8"))
    arms = rescore.load_run(RUN_002)
    for arm, rows in arms.items():
        got = rescore.score_records(rows).injection.as_dict()
        expected = summary["arms"][arm]["detection"]
        assert got == expected, f"{arm} detection metrics drifted from summary.json"


@pytest.mark.skipif(not RUN_002.exists(), reason="run_002 results not present")
def test_reproduces_hand_computed_run_002_correctness_decomposition():
    """Pins the tool to the hand-derived numbers in the analysis document.

    ANALYSIS_REPAIR_POLICY_AND_FPR.md reports, for the deminh arm's 186
    non-injected records: 150 flagged, of which 89 were genuinely wrong, 60
    genuinely right and 1 had no gold answer; and 36 unflagged, of which 22
    were wrong. That is scope='clean' on the pre-verification answer, and it
    yields precision 0.5973 and recall 0.8018.
    """
    rows = rescore.load_run(RUN_002)["deminh"]
    score = rescore.score_records(rows, scope="clean",
                                  answer_field="pre_verification_answer")
    m = score.correctness
    assert (m.tp, m.fp, m.fn, m.tn) == (89, 60, 22, 14)
    assert score.n_no_gold == 1
    assert m.precision == pytest.approx(0.5973, abs=5e-5)
    assert m.recall == pytest.approx(0.8018, abs=5e-5)
    # and the injection-based precision it is contrasted against
    assert score.injection.precision == pytest.approx(0.4485, abs=5e-5)
