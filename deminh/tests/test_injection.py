import pytest

from deminh.injection import ErrorCategory, InjectionConfig, InjectionHarness
from deminh.schemas import (Derivation, Figure, NumericClaim, PipelineRecord,
                            Provenance)


def _record():
    record = PipelineRecord(question_id="q", question="?",
                            context="Revenue 200\nNet income 25")
    rev = Figure(label="revenue", value=200.0,
                 provenance=Provenance(doc_id="d", location="t1",
                                       source_text="Revenue 200"))
    inc = Figure(label="net income", value=25.0,
                 provenance=Provenance(doc_id="d", location="t2",
                                       source_text="Net income 25"))
    record.figures = [rev, inc]
    derivation = Derivation(expression="(inc / rev) * 100",
                            bindings={"inc": inc.id, "rev": rev.id},
                            claimed_result=12.5)
    record.claims = [NumericClaim(value=12.5, surface_text="12.5",
                                  derivation=derivation,
                                  figure_ids=[inc.id, rev.id])]
    return record


@pytest.fixture
def harness():
    return InjectionHarness(InjectionConfig(categories=list(ErrorCategory), seed=1))


@pytest.mark.parametrize("category", list(ErrorCategory))
def test_every_category_produces_labelled_ground_truth(harness, category):
    record = _record()
    injection = harness.corrupt_with(record, category)
    assert injection is not None, f"{category} failed to inject"
    assert injection.category == category.value
    assert injection.original_value != injection.corrupted_value


def test_wrong_extraction_keeps_value_traceable(harness):
    """The corrupted figure must still be a real number from the document.

    If injection produced an untraceable value, provenance would catch it and
    the category would no longer test what it claims to test.
    """
    record = _record()
    harness.corrupt_with(record, ErrorCategory.WRONG_EXTRACTION)
    from deminh.verification.provenance import check_figure
    for figure in record.figures:
        assert check_figure(figure, record.context) is None


def test_injection_rate_is_reproducible():
    a = InjectionHarness(InjectionConfig(categories=list(ErrorCategory), seed=99))
    b = InjectionHarness(InjectionConfig(categories=list(ErrorCategory), seed=99))
    ra, rb = _record(), _record()
    a.maybe_corrupt(ra)
    b.maybe_corrupt(rb)
    assert len(ra.injected) == len(rb.injected)
