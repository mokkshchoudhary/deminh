"""Mechanism 3: cross-derivation against accounting identities.

The only mechanism that can catch a *semantically* wrong figure. If the Extractor
returns net sales where net income was wanted, recomputation is satisfied and
provenance is satisfied — the number is real and the arithmetic is correct. But
the balance sheet will not balance.

DECISION POINT. The identity set below is deliberately small and generic. Which
identities you encode determines what your third mechanism can catch, and
therefore shapes your headline result. Two things to do before you build on this:

  1. Run `measure_coverage()` over a FinQA / TAT-QA sample and report the number.
     This is the open item in your notes (FR5 coverage). If only 8% of questions
     admit an identity check, that is a finding to report honestly, not a flaw to
     hide — and it bounds what the mechanism can contribute.
  2. Justify the chosen identities from an accounting source and cite it. An
     examiner can reasonably ask why these and not others.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..numeric import close_enough, normalise_label
from ..schemas import Figure, Flag, Mechanism, NumericClaim, PipelineRecord, Severity


# Synonym sets: filings use inconsistent line-item wording.
SYNONYMS: dict[str, set[str]] = {
    "assets": {"assets", "asset"},
    "liabilities": {"liabilities", "liability"},
    "equity": {"equity", "shareholders equity", "stockholders equity",
               "shareholders investment", "owners equity"},
    "revenue": {"revenue", "revenues", "sales", "sales revenue", "turnover"},
    "cogs": {"cost sales", "cost goods sold", "cogs", "cost revenue"},
    "gross_profit": {"gross profit", "gross margin"},
    "operating_income": {"operating income", "operating profit", "income operations"},
    "operating_expenses": {"operating expenses", "opex"},
    "net_income": {"income", "net income", "profit", "earnings", "net earnings"},
    "current_assets": {"current assets"},
    "current_liabilities": {"current liabilities"},
}


@dataclass
class Identity:
    """An accounting relationship that must hold among named line items."""

    name: str
    target: str                 # canonical name of the derived quantity
    components: list[str]       # canonical names of the inputs
    expression: str             # arithmetic over component names
    tolerance: float = 5e-3     # filings round; be generous or drown in false positives
    source: str = ""            # cite where the identity comes from


DEFAULT_IDENTITIES: list[Identity] = [
    Identity(
        name="balance_sheet",
        target="assets",
        components=["liabilities", "equity"],
        expression="liabilities + equity",
        source="Fundamental accounting equation.",
    ),
    Identity(
        name="gross_profit",
        target="gross_profit",
        components=["revenue", "cogs"],
        expression="revenue - cogs",
    ),
    Identity(
        name="operating_income",
        target="operating_income",
        components=["gross_profit", "operating_expenses"],
        expression="gross_profit - operating_expenses",
    ),
    # ADD YOUR OWN HERE. Candidates worth considering: working capital,
    # current ratio consistency, retained earnings roll-forward,
    # EPS = net income / weighted average shares.
]


def _canonical(label: str) -> Optional[str]:
    norm = normalise_label(label)
    for canon, variants in SYNONYMS.items():
        if norm in {normalise_label(v) for v in variants}:
            return canon
    # Fall back to substring containment, which is looser and noisier.
    for canon, variants in SYNONYMS.items():
        for variant in variants:
            if normalise_label(variant) and normalise_label(variant) in norm:
                return canon
    return None


def index_figures(figures: list[Figure]) -> dict[str, Figure]:
    """Map canonical line-item name -> Figure. Later figures win on collision."""
    index: dict[str, Figure] = {}
    for figure in figures:
        canon = _canonical(figure.label)
        if canon:
            index[canon] = figure
    return index


def applicable(identity: Identity, index: dict[str, Figure]) -> bool:
    needed = set(identity.components) | {identity.target}
    return needed.issubset(index.keys())


def check_record(record: PipelineRecord,
                 identities: Optional[list[Identity]] = None) -> tuple[bool, list[Flag]]:
    """Apply every applicable identity. Returns (any_applied, flags)."""
    from .recompute import safe_eval, ExpressionError

    identities = identities or DEFAULT_IDENTITIES
    index = index_figures(record.figures)
    flags: list[Flag] = []
    applied = False

    # Attribute identity violations to the claims that depend on the figures
    # involved; if none do, attribute to every claim, since the underlying
    # extraction is unsound.
    for identity in identities:
        if not applicable(identity, index):
            continue
        applied = True
        variables = {name: index[name].value for name in identity.components}
        try:
            expected = safe_eval(identity.expression, variables)
        except ExpressionError:
            continue

        actual = index[identity.target].value
        if close_enough(expected, actual, rel_tol=identity.tolerance):
            continue

        message = (
            f"Identity {identity.name!r} violated: {identity.target} = {actual} "
            f"but {identity.expression} = {expected}."
        )
        involved = {index[n].id for n in identity.components} | {index[identity.target].id}
        targets = [c for c in record.claims if involved.intersection(c.figure_ids)]
        for claim in targets or record.claims:
            flags.append(Flag(
                claim_id=claim.id,
                mechanism=Mechanism.IDENTITY,
                message=message,
                severity=Severity.ERROR,
            ))

    return applied, flags


def measure_coverage(records: list[PipelineRecord],
                     identities: Optional[list[Identity]] = None) -> dict[str, float]:
    """What fraction of records admit at least one identity check?

    Run this before you rely on the mechanism. Report the number in the
    dissertation. It is the honest bound on what cross-derivation can contribute.
    """
    identities = identities or DEFAULT_IDENTITIES
    per_identity = {i.name: 0 for i in identities}
    any_applicable = 0

    for record in records:
        index = index_figures(record.figures)
        hit = False
        for identity in identities:
            if applicable(identity, index):
                per_identity[identity.name] += 1
                hit = True
        any_applicable += int(hit)

    total = max(len(records), 1)
    result = {f"coverage_{name}": count / total for name, count in per_identity.items()}
    result["coverage_any"] = any_applicable / total
    result["n_records"] = float(len(records))
    return result
