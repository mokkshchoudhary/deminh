"""Typed data structures shared by every stage of the DeMiNH pipeline.

Design note (important for the dissertation): numbers move through this system
as *structured objects carrying their origin*, never as bare floats embedded in
prose. This is what makes provenance tracing possible at all. If you let the
Analyst emit free text containing digits, you lose the ability to check anything
deterministically and the whole independence argument collapses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# Provenance and figures
# --------------------------------------------------------------------------

@dataclass
class Provenance:
    """Where a figure came from in the source document."""

    doc_id: str
    location: str          # e.g. "table_2:row_4:col_2" or "para_11"
    source_text: str       # the raw span the value was read from
    extraction_method: str = "llm"   # "llm" | "table_lookup" | "derived"

    def is_traceable(self) -> bool:
        return bool(self.doc_id and self.source_text)


@dataclass
class Figure:
    """A single atomic number lifted from a source document."""

    label: str                     # e.g. "net income"
    value: float                   # normalised to base units (see numeric.py)
    provenance: Provenance
    id: str = field(default_factory=lambda: _new_id("fig"))
    unit: str = "USD"
    scale: float = 1.0             # multiplier already applied to `value`
    period: Optional[str] = None   # e.g. "FY2019"

    def key(self) -> str:
        return f"{self.label.strip().lower()}|{self.period or ''}"


# --------------------------------------------------------------------------
# Derivations and claims
# --------------------------------------------------------------------------

@dataclass
class Derivation:
    """How a computed number was produced.

    `expression` is an arithmetic string over figure labels bound in `bindings`,
    e.g. "(net_income / revenue) * 100". It is re-evaluated independently by
    verification.recompute — never by the model that wrote it.
    """

    expression: str
    bindings: dict[str, str]        # variable name -> Figure.id
    claimed_result: float
    id: str = field(default_factory=lambda: _new_id("der"))
    operation_label: str = ""       # e.g. "profit margin"


@dataclass
class NumericClaim:
    """A number as asserted in the final answer."""

    value: float
    surface_text: str                       # how it appears in the write-up
    id: str = field(default_factory=lambda: _new_id("clm"))
    derivation: Optional[Derivation] = None
    figure_ids: list[str] = field(default_factory=list)
    unit: str = "USD"


# --------------------------------------------------------------------------
# Verification output
# --------------------------------------------------------------------------

class Mechanism(str, Enum):
    RECOMPUTE = "recompute"
    PROVENANCE = "provenance"
    IDENTITY = "identity"
    SELF_CHECK = "self_check"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class Flag:
    """One mechanism's objection to one claim."""

    claim_id: str
    mechanism: Mechanism
    message: str
    severity: Severity = Severity.ERROR
    proposed_value: Optional[float] = None   # None => detected but not repairable


@dataclass
class VerificationReport:
    flags: list[Flag] = field(default_factory=list)
    claims_checked: list[str] = field(default_factory=list)
    claims_uncovered: list[str] = field(default_factory=list)  # no mechanism applied
    repairs: dict[str, float] = field(default_factory=dict)    # claim_id -> new value

    @property
    def flagged_claim_ids(self) -> set[str]:
        return {f.claim_id for f in self.flags if f.severity is Severity.ERROR}

    def coverage(self) -> float:
        """Fraction of claims that at least one mechanism could speak to.

        Reporting this matters: a verifier that only covers 30% of claims may
        look precise while catching almost nothing. Open item FR5 in your notes.
        """
        total = len(self.claims_checked) + len(self.claims_uncovered)
        return len(self.claims_checked) / total if total else 0.0


# --------------------------------------------------------------------------
# Pipeline record
# --------------------------------------------------------------------------

@dataclass
class PipelineRecord:
    """Everything produced for a single question. This is the unit of evaluation."""

    question_id: str
    question: str
    context: str
    gold_answer: Optional[float] = None

    figures: list[Figure] = field(default_factory=list)
    claims: list[NumericClaim] = field(default_factory=list)
    final_answer: Optional[float] = None
    answer_text: str = ""

    report: Optional[VerificationReport] = None
    injected: list["InjectionRecord"] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def figure_by_id(self, fid: str) -> Optional[Figure]:
        return next((f for f in self.figures if f.id == fid), None)

    def claim_by_id(self, cid: str) -> Optional[NumericClaim]:
        return next((c for c in self.claims if c.id == cid), None)


@dataclass
class InjectionRecord:
    """Ground truth for the detection experiment: what was corrupted, and how."""

    target_id: str          # Figure.id or NumericClaim.id
    target_kind: str        # "figure" | "claim"
    category: str           # ErrorCategory value
    original_value: float
    corrupted_value: float
    affected_claim_ids: list[str] = field(default_factory=list)
