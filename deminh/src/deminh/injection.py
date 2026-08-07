"""The error injection harness.

This is the instrument that makes the experiment measurable, and it deserves a
section of its own in the dissertation.

Why inject at all? Because you cannot compute recall on naturally-occurring
hallucinations without knowing which outputs were wrong, and hand-labelling
enough of them is not feasible in an MSc timeframe. Injection gives you exact
ground truth: you know which number you broke, and how.

The critical property, stated in your own notes: THE CATEGORIES YOU INJECT ARE
THE CATEGORIES YOU CAN REPORT ON. Decide the taxonomy before you build, justify
it, and do not change it midway. The six below are a proposal, not a decision —
argue for or against each, and defend the final set to your supervisor.

The honest limitation to state up front: injected errors are a proxy for natural
ones. Synthetic corruption may be easier or harder to catch than what an 8B model
actually gets wrong. Mitigate this by hand-labelling a small sample of *natural*
pipeline errors and reporting how their category distribution compares to your
injected distribution. That comparison turns a methodological weakness into a
piece of analysis.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .schemas import Figure, InjectionRecord, NumericClaim, PipelineRecord, Provenance

log = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    ARITHMETIC_SLIP = "arithmetic_slip"      # right inputs, right operation, wrong sum
    WRONG_EXTRACTION = "wrong_extraction"    # a real number, but the wrong line item
    WRONG_OPERATION = "wrong_operation"      # right inputs, wrong operation
    INVENTED_FIGURE = "invented_figure"      # a number that is not in the document
    SCALE_ERROR = "scale_error"              # thousands read as millions
    SIGN_ERROR = "sign_error"                # parenthesised negative read as positive


# Which mechanism *should* catch which category. Stating this as a prediction
# before you run the experiment is good practice: it turns your results into a
# test of a hypothesis rather than a description of whatever happened.
EXPECTED_CATCHER: dict[ErrorCategory, list[str]] = {
    ErrorCategory.ARITHMETIC_SLIP: ["recompute"],
    ErrorCategory.WRONG_EXTRACTION: ["identity"],
    ErrorCategory.WRONG_OPERATION: ["identity"],
    ErrorCategory.INVENTED_FIGURE: ["provenance"],
    ErrorCategory.SCALE_ERROR: ["provenance", "identity"],
    ErrorCategory.SIGN_ERROR: ["provenance", "identity"],
}


@dataclass
class InjectionConfig:
    categories: list[ErrorCategory]
    rate: float = 0.5          # fraction of records to corrupt
    seed: int = 1234
    magnitude: float = 0.15    # relative perturbation for arithmetic slips


class InjectionHarness:
    def __init__(self, config: InjectionConfig):
        self.config = config
        self.rng = random.Random(config.seed)
        self._injectors: dict[ErrorCategory, Callable[[PipelineRecord], Optional[InjectionRecord]]] = {
            ErrorCategory.ARITHMETIC_SLIP: self._arithmetic_slip,
            ErrorCategory.WRONG_EXTRACTION: self._wrong_extraction,
            ErrorCategory.WRONG_OPERATION: self._wrong_operation,
            ErrorCategory.INVENTED_FIGURE: self._invented_figure,
            ErrorCategory.SCALE_ERROR: self._scale_error,
            ErrorCategory.SIGN_ERROR: self._sign_error,
        }

    def maybe_corrupt(self, record: PipelineRecord) -> PipelineRecord:
        """Corrupt with probability `rate`. Records are mutated in place."""
        if self.rng.random() >= self.config.rate:
            return record
        category = self.rng.choice(self.config.categories)
        injection = self._injectors[category](record)
        if injection is not None:
            record.injected.append(injection)
        return record

    def corrupt_with(self, record: PipelineRecord,
                     category: ErrorCategory) -> Optional[InjectionRecord]:
        """Force a specific category. Use for balanced per-category test sets.

        The record is not guaranteed to admit this category (e.g. wrong_operation
        needs an arithmetic expression to corrupt; a direct value lookup has
        none). When that happens the injector returns None and the record is
        left uncorrupted with no other signal — log it so the applicability
        gap is measurable per category instead of silently thinning the
        balanced round-robin.
        """
        injection = self._injectors[category](record)
        if injection is not None:
            record.injected.append(injection)
        else:
            log.info("Category %s did not apply to %s; record left uncorrupted.",
                      category.value, record.question_id)
        return injection

    # -- individual injectors ---------------------------------------------

    def _first_claim(self, record: PipelineRecord) -> Optional[NumericClaim]:
        return record.claims[0] if record.claims else None

    def _arithmetic_slip(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        claim = self._first_claim(record)
        if claim is None or claim.value == 0:
            return None
        original = claim.value
        delta = self.config.magnitude * abs(original)
        claim.value = original + self.rng.choice([-1, 1]) * delta
        return InjectionRecord(
            target_id=claim.id, target_kind="claim",
            category=ErrorCategory.ARITHMETIC_SLIP.value,
            original_value=original, corrupted_value=claim.value,
            affected_claim_ids=[claim.id],
        )

    def _wrong_extraction(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        """Swap one figure's value for another real figure's value.

        The number stays genuine and traceable — only the *mapping* is wrong.
        Recomputation and provenance are both satisfied. Only cross-derivation
        has any chance here, which is the whole argument for the third mechanism.
        """
        if len(record.figures) < 2:
            return None
        target, donor = self.rng.sample(record.figures, 2)
        if target.value == donor.value:
            return None
        original = target.value
        target.value = donor.value
        target.provenance = Provenance(
            doc_id=donor.provenance.doc_id,
            location=donor.provenance.location,
            source_text=donor.provenance.source_text,
            extraction_method="llm",
        )
        return InjectionRecord(
            target_id=target.id, target_kind="figure",
            category=ErrorCategory.WRONG_EXTRACTION.value,
            original_value=original, corrupted_value=target.value,
            affected_claim_ids=[c.id for c in record.claims if target.id in c.figure_ids],
        )

    def _wrong_operation(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        claim = self._first_claim(record)
        if claim is None or claim.derivation is None:
            log.debug("wrong_operation: %s has no claim/derivation to corrupt.",
                      record.question_id)
            return None
        expression = claim.derivation.expression
        swaps = [("+", "-"), ("-", "+"), ("*", "/"), ("/", "*")]
        if not any(old in expression for old, _ in swaps):
            log.debug("wrong_operation: %s expression %r has no +-*/ to swap "
                      "(likely a direct lookup, not a derivation).",
                      record.question_id, expression)
            return None
        for old, new in swaps:
            if old in expression:
                original_expr = expression
                claim.derivation.expression = expression.replace(old, new, 1)
                original = claim.value
                # The reported value follows the corrupted plan, so recomputation
                # of the corrupted expression agrees with it. This is deliberate:
                # a wrong operation executed faithfully is invisible to
                # recomputation, and that is the finding worth reporting.
                from .verification.recompute import ExpressionError, safe_eval
                variables = {
                    var: record.figure_by_id(fid).value
                    for var, fid in claim.derivation.bindings.items()
                    if record.figure_by_id(fid) is not None
                }
                try:
                    claim.value = safe_eval(claim.derivation.expression, variables)
                except (ExpressionError, ZeroDivisionError) as exc:
                    log.debug("wrong_operation: %s swap %r->%r made expression "
                              "%r unevaluable (%s); reverted.",
                              record.question_id, old, new,
                              claim.derivation.expression, exc)
                    claim.derivation.expression = original_expr
                    return None
                return InjectionRecord(
                    target_id=claim.id, target_kind="claim",
                    category=ErrorCategory.WRONG_OPERATION.value,
                    original_value=original, corrupted_value=claim.value,
                    affected_claim_ids=[claim.id],
                )
        return None

    def _invented_figure(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        """Insert a figure that appears nowhere in the source, and use it."""
        claim = self._first_claim(record)
        if claim is None or not record.figures:
            return None
        fabricated_value = round(self.rng.uniform(1_000, 9_999_999), 2)
        fabricated = Figure(
            label="adjusted operating figure",
            value=fabricated_value,
            provenance=Provenance(
                doc_id=record.question_id,
                location="table_9:row_9",
                source_text=f"Adjusted operating figure {fabricated_value:,.2f}",
                extraction_method="llm",
            ),
        )
        record.figures.append(fabricated)
        original = claim.value
        claim.figure_ids.append(fabricated.id)
        claim.value = fabricated_value
        return InjectionRecord(
            target_id=fabricated.id, target_kind="figure",
            category=ErrorCategory.INVENTED_FIGURE.value,
            original_value=original, corrupted_value=fabricated_value,
            affected_claim_ids=[claim.id],
        )

    def _scale_error(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        if not record.figures:
            return None
        figure = self.rng.choice(record.figures)
        original = figure.value
        factor = self.rng.choice([1e3, 1e-3, 1e6, 1e-6])
        figure.value = original * factor
        return InjectionRecord(
            target_id=figure.id, target_kind="figure",
            category=ErrorCategory.SCALE_ERROR.value,
            original_value=original, corrupted_value=figure.value,
            affected_claim_ids=[c.id for c in record.claims if figure.id in c.figure_ids],
        )

    def _sign_error(self, record: PipelineRecord) -> Optional[InjectionRecord]:
        candidates = [f for f in record.figures if f.value != 0]
        if not candidates:
            return None
        figure = self.rng.choice(candidates)
        original = figure.value
        figure.value = -original
        return InjectionRecord(
            target_id=figure.id, target_kind="figure",
            category=ErrorCategory.SIGN_ERROR.value,
            original_value=original, corrupted_value=figure.value,
            affected_claim_ids=[c.id for c in record.claims if figure.id in c.figure_ids],
        )
