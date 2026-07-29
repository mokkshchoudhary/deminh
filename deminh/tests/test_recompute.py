import pytest

from deminh.schemas import (Derivation, Figure, NumericClaim, PipelineRecord,
                            Provenance)
from deminh.verification.recompute import (ExpressionError, check_claim,
                                           safe_eval)


def test_evaluates_arithmetic():
    assert safe_eval("(a / b) * 100", {"a": 25.0, "b": 200.0}) == 12.5


def test_rejects_attribute_access():
    with pytest.raises(ExpressionError):
        safe_eval("().__class__", {})


def test_rejects_unknown_function():
    with pytest.raises(ExpressionError):
        safe_eval("exec('x=1')", {})


def test_rejects_unbound_variable():
    with pytest.raises(ExpressionError):
        safe_eval("a + b", {"a": 1.0})


def test_rejects_division_by_zero():
    with pytest.raises(ExpressionError):
        safe_eval("a / b", {"a": 1.0, "b": 0.0})


def _record():
    prov = Provenance(doc_id="d1", location="t1", source_text="Revenue 200")
    rev = Figure(label="revenue", value=200.0, provenance=prov)
    inc = Figure(label="net income", value=25.0,
                 provenance=Provenance(doc_id="d1", location="t2",
                                       source_text="Net income 25"))
    record = PipelineRecord(question_id="q1", question="margin?",
                            context="Revenue 200\nNet income 25")
    record.figures = [rev, inc]
    return record, rev, inc


def test_flags_arithmetic_slip_and_proposes_repair():
    record, rev, inc = _record()
    derivation = Derivation(expression="(inc / rev) * 100",
                            bindings={"inc": inc.id, "rev": rev.id},
                            claimed_result=99.0)
    claim = NumericClaim(value=99.0, surface_text="99%", derivation=derivation,
                         figure_ids=[inc.id, rev.id])
    record.claims = [claim]

    checkable, flag = check_claim(claim, record)
    assert checkable
    assert flag is not None
    assert flag.proposed_value == 12.5


def test_passes_correct_claim():
    record, rev, inc = _record()
    derivation = Derivation(expression="(inc / rev) * 100",
                            bindings={"inc": inc.id, "rev": rev.id},
                            claimed_result=12.5)
    claim = NumericClaim(value=12.5, surface_text="12.5%", derivation=derivation,
                         figure_ids=[inc.id, rev.id])
    record.claims = [claim]
    checkable, flag = check_claim(claim, record)
    assert checkable and flag is None
