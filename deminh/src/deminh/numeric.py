"""Parsing and comparison of financial numbers.

This module is dull and load-bearing. Most naive verification failures in
financial QA are not reasoning failures — they are formatting failures. A
verifier that flags 1,234 against "$1.234 million" as a mismatch produces false
positives that swamp its real detections, and your false-positive rate is one of
the headline metrics.
"""

from __future__ import annotations

import re
from typing import Iterator, Optional

# Words that multiply a figure. Financial filings mix these freely.
SCALE_WORDS: dict[str, float] = {
    "hundred": 1e2,
    "thousand": 1e3,
    "thousands": 1e3,
    "k": 1e3,
    "million": 1e6,
    "millions": 1e6,
    "mm": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "billions": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
}

_NUMBER_RE = re.compile(
    r"""
    (?P<paren>\()?                 # accounting negative: (1,234)
    \s*
    (?P<currency>[$£€])?
    \s*
    (?P<sign>[-+])?
    (?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*
    (?P<percent>%)?
    \s*
    (?P<scale>hundred|thousands?|millions?|billions?|trillion|bn|mm|[kmb])?\b
    \s*
    (?P<close>\))?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_number(text: str) -> Optional[float]:
    """Parse the first number in `text` into a plain float, or None."""
    for value in iter_numbers(text):
        return value
    return None


def iter_numbers(text: str) -> Iterator[float]:
    """Yield every number found in `text`, normalised to base units."""
    for match in _NUMBER_RE.finditer(text or ""):
        digits = match.group("digits").replace(",", "")
        try:
            value = float(digits)
        except ValueError:  # pragma: no cover - regex guarantees digits
            continue

        scale = match.group("scale")
        if scale:
            value *= SCALE_WORDS[scale.lower()]

        negative = match.group("sign") == "-"
        # Accounting convention: a fully parenthesised figure is negative.
        if match.group("paren") and match.group("close"):
            negative = True
        if negative:
            value = -value

        yield value


def close_enough(a: float, b: float, rel_tol: float = 1e-3, abs_tol: float = 1e-6) -> bool:
    """Tolerant equality. Rounding in filings is routine; exact match is wrong."""
    if a is None or b is None:
        return False
    if abs(a - b) <= abs_tol:
        return True
    denom = max(abs(a), abs(b))
    return denom > 0 and abs(a - b) / denom <= rel_tol


def same_up_to_scale(a: float, b: float, rel_tol: float = 1e-3) -> Optional[float]:
    """If a and b differ only by a power-of-ten scale factor, return that factor.

    Used to distinguish a genuine wrong number from a units/scale error, which is
    a distinct error category and behaves very differently under recomputation.
    """
    if not a or not b:
        return None
    for factor in (1e-3, 1e-2, 1e-1, 1e1, 1e2, 1e3, 1e6, 1e9):
        if close_enough(a * factor, b, rel_tol=rel_tol):
            return factor
    return None


def appears_in(value: float, text: str, rel_tol: float = 1e-3) -> bool:
    """True if `value` is present in `text` under any reasonable formatting."""
    for candidate in iter_numbers(text):
        if close_enough(candidate, value, rel_tol=rel_tol):
            return True
        # A figure written as "1.2" in a table headed "in millions".
        if same_up_to_scale(candidate, value, rel_tol=rel_tol) is not None:
            return True
    return False


def normalise_label(label: str) -> str:
    """Canonicalise a line-item label for identity matching."""
    label = (label or "").strip().lower()
    label = re.sub(r"[^a-z0-9 ]+", " ", label)
    label = re.sub(r"\b(total|net|the|of|for|and)\b", " ", label)
    return re.sub(r"\s+", " ", label).strip()
