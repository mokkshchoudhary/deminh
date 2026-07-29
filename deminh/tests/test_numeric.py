from deminh.numeric import (appears_in, close_enough, normalise_label,
                            parse_number, same_up_to_scale)


def test_parses_comma_grouped():
    assert parse_number("1,234,567") == 1234567.0


def test_parses_accounting_negative():
    assert parse_number("(1,234)") == -1234.0


def test_parses_scale_words():
    assert parse_number("$1.5 million") == 1_500_000.0
    assert parse_number("2 bn") == 2_000_000_000.0


def test_close_enough_tolerates_rounding():
    assert close_enough(1234.0, 1234.4, rel_tol=1e-3)
    assert not close_enough(1234.0, 1300.0, rel_tol=1e-3)


def test_same_up_to_scale_detects_thousands():
    assert same_up_to_scale(1.234, 1234.0) == 1e3


def test_appears_in_handles_formatting():
    assert appears_in(1234.0, "Net income  1,234")
    assert not appears_in(9999.0, "Net income  1,234")


def test_normalise_label_strips_qualifiers():
    assert normalise_label("Total Shareholders' Equity") == "shareholders equity"
