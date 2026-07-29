from deminh.schemas import Figure, PipelineRecord, Provenance
from deminh.verification.provenance import check_figure

DOC = "Consolidated results\nNet income  1,234\nRevenue  10,000\n"


def test_accepts_grounded_figure():
    fig = Figure(label="net income", value=1234.0,
                 provenance=Provenance(doc_id="d", location="t1",
                                       source_text="Net income  1,234"))
    assert check_figure(fig, DOC) is None


def test_rejects_invented_figure():
    fig = Figure(label="adjusted ebitda", value=555555.0,
                 provenance=Provenance(doc_id="d", location="t9",
                                       source_text="Adjusted EBITDA 555,555"))
    problem = check_figure(fig, DOC)
    assert problem is not None and "does not appear verbatim" in problem


def test_rejects_value_absent_from_its_own_span():
    fig = Figure(label="net income", value=9999.0,
                 provenance=Provenance(doc_id="d", location="t1",
                                       source_text="Net income  1,234"))
    problem = check_figure(fig, DOC)
    assert problem is not None


def test_rejects_untraceable_figure():
    fig = Figure(label="mystery", value=1.0,
                 provenance=Provenance(doc_id="", location="", source_text=""))
    assert check_figure(fig, DOC) is not None
