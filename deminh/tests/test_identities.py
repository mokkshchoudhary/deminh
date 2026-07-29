from deminh.schemas import Figure, NumericClaim, PipelineRecord, Provenance
from deminh.verification.identities import (applicable, check_record,
                                            index_figures, measure_coverage,
                                            DEFAULT_IDENTITIES)


def _fig(label, value):
    return Figure(label=label, value=value,
                  provenance=Provenance(doc_id="d", location="l",
                                        source_text=f"{label} {value}"))


def _record(assets):
    record = PipelineRecord(question_id="q", question="?", context="ctx")
    record.figures = [
        _fig("Total assets", assets),
        _fig("Total liabilities", 60.0),
        _fig("Total shareholders equity", 40.0),
    ]
    record.claims = [NumericClaim(value=assets, surface_text="assets",
                                  figure_ids=[record.figures[0].id])]
    return record


def test_indexes_synonyms():
    index = index_figures(_record(100.0).figures)
    assert {"assets", "liabilities", "equity"}.issubset(index.keys())


def test_balance_sheet_identity_holds():
    applied, flags = check_record(_record(100.0))
    assert applied and flags == []


def test_balance_sheet_identity_violated():
    applied, flags = check_record(_record(180.0))
    assert applied
    assert any("balance_sheet" in f.message for f in flags)


def test_coverage_is_reported():
    stats = measure_coverage([_record(100.0), _record(180.0)])
    assert stats["coverage_any"] == 1.0
    assert stats["n_records"] == 2.0


def test_coverage_zero_when_no_line_items_match():
    empty = PipelineRecord(question_id="q", question="?", context="c")
    empty.figures = [_fig("headcount", 5.0)]
    stats = measure_coverage([empty])
    assert stats["coverage_any"] == 0.0
