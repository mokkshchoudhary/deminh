from deminh.metrics import (ConfusionMatrix, detection_by_category,
                            detection_metrics, mcnemar, mitigation_metrics)
from deminh.schemas import (Flag, InjectionRecord, Mechanism, NumericClaim,
                            PipelineRecord, Severity, VerificationReport)


def _record(qid, corrupted, flagged, gold=10.0, before=10.0, after=10.0):
    record = PipelineRecord(question_id=qid, question="?", context="c",
                            gold_answer=gold)
    claim = NumericClaim(value=after, surface_text="x")
    record.claims = [claim]
    record.final_answer = after
    record.meta["pre_verification_answer"] = before
    if corrupted:
        record.injected.append(InjectionRecord(
            target_id=claim.id, target_kind="claim", category="arithmetic_slip",
            original_value=10.0, corrupted_value=12.0))
    report = VerificationReport(claims_checked=[claim.id])
    if flagged:
        report.flags.append(Flag(claim_id=claim.id, mechanism=Mechanism.RECOMPUTE,
                                 message="m", severity=Severity.ERROR))
    record.report = report
    return record


def test_confusion_matrix_arithmetic():
    matrix = ConfusionMatrix(tp=8, fp=2, fn=2, tn=88)
    assert matrix.precision == 0.8
    assert matrix.recall == 0.8
    assert abs(matrix.f1 - 0.8) < 1e-9
    assert abs(matrix.false_positive_rate - 2 / 90) < 1e-9


def test_detection_metrics_counts_all_four_cells():
    records = [_record("a", True, True), _record("b", True, False),
               _record("c", False, True), _record("d", False, False)]
    matrix = detection_metrics(records)
    assert (matrix.tp, matrix.fn, matrix.fp, matrix.tn) == (1, 1, 1, 1)


def test_detection_by_category_reports_recall():
    records = [_record("a", True, True), _record("b", True, False)]
    breakdown = detection_by_category(records)
    assert breakdown["arithmetic_slip"] == {"n": 2, "recall": 0.5}


def test_mitigation_separates_repair_from_harm():
    records = [
        _record("a", True, True, gold=10.0, before=12.0, after=10.0),   # repaired
        _record("b", False, True, gold=10.0, before=10.0, after=13.0),  # harmed
        _record("c", False, False, gold=10.0, before=10.0, after=10.0), # untouched
    ]
    metrics = mitigation_metrics(records)
    assert metrics.repaired == 1
    assert metrics.harmed == 1
    assert metrics.n == 3


def test_mcnemar_uses_only_discordant_pairs():
    a = [True, True, False, True, False]
    b = [False, True, False, False, False]
    result = mcnemar(a, b)
    assert (result.b, result.c) == (2, 0)
    assert result.n_discordant == 2


def test_mcnemar_identical_arms_give_p_one():
    outcomes = [True, False, True]
    result = mcnemar(outcomes, outcomes)
    assert result.p_value == 1.0
