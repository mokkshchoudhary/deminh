"""Mechanism 2: provenance tracing.

Every figure claims a source span. This mechanism checks that the figure's value
actually occurs in that span, and that the span actually occurs in the document.

Catches: invented figures (the classic hallucination — a number that appears
nowhere in the source), and figures copied with a transcription or scale error.

Does NOT catch: a figure that is genuinely present in the document but is the
wrong line item. "Net sales" instead of "net income" traces perfectly. That
error type needs cross-derivation, which is why the mechanisms are not
redundant.

This mechanism cannot repair. It knows a number is unsupported; it does not know
what the number should have been. That asymmetry is worth reporting: detection
rate and repair rate are different quantities and should be tabulated separately.
"""

from __future__ import annotations

from typing import Optional

from ..numeric import appears_in, same_up_to_scale
from ..schemas import Figure, Flag, Mechanism, NumericClaim, PipelineRecord, Severity


def check_figure(figure: Figure, document: str) -> Optional[str]:
    """Return an error message if the figure is not properly grounded."""
    prov = figure.provenance

    if not prov.is_traceable():
        return f"Figure {figure.label!r} carries no source span."

    # The quoted span must genuinely come from the document. Models paraphrase
    # source text when asked to copy it; normalise whitespace before comparing.
    span = " ".join(prov.source_text.split())
    haystack = " ".join((document or "").split())
    if span and span not in haystack:
        return (
            f"Figure {figure.label!r} cites a span that does not appear verbatim "
            f"in the document: {prov.source_text[:80]!r}"
        )

    # The value must appear in the span it was supposedly read from.
    raw_value = figure.value / figure.scale if figure.scale else figure.value
    if not (appears_in(figure.value, prov.source_text)
            or appears_in(raw_value, prov.source_text)):
        return (
            f"Figure {figure.label!r} has value {figure.value} which does not "
            f"appear in its cited span {prov.source_text[:80]!r}"
        )

    # Distinguish a scale slip from an outright fabrication, for the category
    # breakdown in the results chapter.
    for candidate in _span_numbers(prov.source_text):
        factor = same_up_to_scale(candidate, figure.value)
        if factor is not None and factor != 1.0:
            return (
                f"Figure {figure.label!r} appears to be off by a factor of "
                f"{factor:g} relative to its source span."
            )
        break

    return None


def _span_numbers(text: str) -> list[float]:
    from ..numeric import iter_numbers
    return list(iter_numbers(text))


def check_claim(claim: NumericClaim, record: PipelineRecord) -> tuple[bool, list[Flag]]:
    """Check every figure the claim depends on."""
    if not claim.figure_ids:
        return False, []

    flags: list[Flag] = []
    for fig_id in claim.figure_ids:
        figure = record.figure_by_id(fig_id)
        if figure is None:
            flags.append(Flag(
                claim_id=claim.id,
                mechanism=Mechanism.PROVENANCE,
                message=f"Claim depends on missing figure {fig_id!r}.",
                severity=Severity.ERROR,
            ))
            continue
        problem = check_figure(figure, record.context)
        if problem:
            flags.append(Flag(
                claim_id=claim.id,
                mechanism=Mechanism.PROVENANCE,
                message=problem,
                severity=Severity.ERROR,
            ))
    return True, flags
