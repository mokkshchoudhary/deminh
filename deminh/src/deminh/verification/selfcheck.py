"""Configuration 2's verifier: the same model checking its own answer.

This is the comparison target, not part of DeMiNH proper. It must be implemented
*well*, not as a straw man. If you give the self-check a deliberately weak prompt
and then report that independent verification wins, the result is worthless and a
careful examiner will say so.

Fairness requirements, which you should state explicitly in the methodology:
  - The self-check sees the same document, the same figures and the same
    derivation the deterministic mechanisms see. No information asymmetry.
  - Same model, same decoding parameters, same seed.
  - The prompt asks for the same output contract (flag / repair) as the
    deterministic layer produces.

The one thing it lacks is independence. That is the variable under test, and it
should be the *only* thing that differs.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..llm import GenerationConfig, LLMBackend
from ..schemas import Flag, Mechanism, NumericClaim, PipelineRecord, Severity

log = logging.getLogger(__name__)

SELF_CHECK_SYSTEM = """You are checking whether a numeric answer is correct.

You are given the source document, the figures that were extracted from it, the
calculation that was planned, and the resulting number.

Decide whether the number is correct. Consider:
- Was each figure read correctly from the document?
- Is each figure the line item it claims to be?
- Is the calculation the right one for the question?
- Is the arithmetic right?

Return ONLY a JSON object:
{
  "verdict": "correct" | "incorrect",
  "reason": "one sentence",
  "corrected_value": 123.45
}

Set "corrected_value" to null if the number is correct, or if it is wrong but
you cannot determine the right value."""


class SelfChecker:
    def __init__(self, backend: LLMBackend, config: Optional[GenerationConfig] = None):
        self.backend = backend
        self.config = config or GenerationConfig()

    def check_claim(self, claim: NumericClaim,
                    record: PipelineRecord) -> tuple[bool, Optional[Flag]]:
        figure_lines = "\n".join(
            f"- {f.label} = {f.value} {f.unit}  [source: {f.provenance.source_text[:120]}]"
            for f in record.figures
        )
        derivation = claim.derivation
        plan = (
            f"{derivation.operation_label}: {derivation.expression}"
            if derivation else "(no explicit calculation recorded)"
        )

        user = (
            f"Question: {record.question}\n\n"
            f"Document:\n{record.context}\n\n"
            f"Extracted figures:\n{figure_lines or '(none)'}\n\n"
            f"Planned calculation: {plan}\n\n"
            f"Answer produced: {claim.value}\n\n"
            "Check it."
        )

        try:
            payload = self.backend.chat_json(SELF_CHECK_SYSTEM, user, self.config)
        except (ValueError, KeyError) as exc:
            log.warning("Self-check unparseable for claim %s: %s", claim.id, exc)
            # An unparseable verdict is not a detection. Counting it as one
            # would inflate the baseline's recall.
            return True, None

        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict != "incorrect":
            return True, None

        corrected = payload.get("corrected_value")
        try:
            proposed = float(corrected) if corrected is not None else None
        except (TypeError, ValueError):
            proposed = None

        return True, Flag(
            claim_id=claim.id,
            mechanism=Mechanism.SELF_CHECK,
            message=str(payload.get("reason", "Self-check judged the value incorrect.")),
            severity=Severity.ERROR,
            proposed_value=proposed,
        )
