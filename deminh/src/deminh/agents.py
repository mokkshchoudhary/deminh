"""The three agents named in the submitted proposal: Extractor, Analyst, Writer.

Note the division of labour, which is the point of the architecture:

  Extractor  reads numbers out of the document and records where each came from.
  Analyst    decides what arithmetic to do, and emits it as an *expression*,
             not as an answer. It does not compute.
  Writer     turns verified figures into prose.

The Analyst emitting an expression rather than a result is what allows the
verifier to be code. If the Analyst returned "the margin is 23.4%", there is
nothing deterministic to re-run. This is the PAL / Program-of-Thoughts idea
(Gao et al.; Chen et al.) applied at the generation stage — settled ground that
you build on, per your own framing. The contribution is the checking stage.

PROMPTS ARE A DECISION POINT. The ones below are functional starting points,
not tuned artefacts. Tune them against your own 8B model, keep the tuned
versions under version control, and report in the dissertation that prompts were
held identical across all three configurations — otherwise prompt quality is a
confound in your comparison.
"""

from __future__ import annotations

import logging
from typing import Optional

from .llm import LLMBackend, GenerationConfig
from .schemas import Derivation, Figure, NumericClaim, PipelineRecord, Provenance

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Extractor
# --------------------------------------------------------------------------

EXTRACTOR_SYSTEM = """You extract financial figures from source documents.

Return ONLY a JSON object of this exact shape:
{
  "figures": [
    {
      "label": "net income",
      "value": 1234.0,
      "scale": 1000000,
      "unit": "USD",
      "period": "FY2019",
      "location": "table_1:row_3",
      "source_text": "Net income  1,234"
    }
  ]
}

Rules:
- "value" is the number exactly as printed, before applying scale.
- "scale" is the multiplier implied by the table heading (1 if none).
- "source_text" MUST be copied verbatim from the document. Never paraphrase it.
- Extract only figures relevant to the question. Do not invent figures.
- If a figure you need is absent, omit it rather than estimating."""


class Extractor:
    def __init__(self, backend: LLMBackend, config: Optional[GenerationConfig] = None):
        self.backend = backend
        self.config = config or GenerationConfig()

    def run(self, record: PipelineRecord) -> list[Figure]:
        user = (
            f"Question: {record.question}\n\n"
            f"Document:\n{record.context}\n\n"
            "Extract the figures needed to answer the question."
        )
        try:
            payload = self.backend.chat_json(EXTRACTOR_SYSTEM, user, self.config)
        except (ValueError, KeyError) as exc:
            log.warning("Extractor produced unparseable output for %s: %s",
                        record.question_id, exc)
            return []

        figures: list[Figure] = []
        for item in payload.get("figures", []):
            try:
                scale = float(item.get("scale", 1) or 1)
                figures.append(
                    Figure(
                        label=str(item["label"]),
                        value=float(item["value"]) * scale,
                        scale=scale,
                        unit=str(item.get("unit", "USD")),
                        period=item.get("period"),
                        provenance=Provenance(
                            doc_id=record.question_id,
                            location=str(item.get("location", "unknown")),
                            source_text=str(item.get("source_text", "")),
                            extraction_method="llm",
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Skipping malformed figure %r: %s", item, exc)
        return figures


# --------------------------------------------------------------------------
# Analyst
# --------------------------------------------------------------------------

ANALYST_SYSTEM = """You plan the arithmetic needed to answer a financial question.

You do NOT calculate. You describe the calculation.

Return ONLY a JSON object of this exact shape:
{
  "expression": "(net_income / revenue) * 100",
  "bindings": {"net_income": "fig_ab12cd34", "revenue": "fig_ef56gh78"},
  "operation_label": "net profit margin",
  "estimated_result": 12.5,
  "unit": "percent"
}

Rules:
- "expression" may use only + - * / ( ) and the functions sum, abs, min, max, round.
- Every variable in the expression MUST appear in "bindings", mapped to a
  figure id from the list you are given.
- Do not put literal figures in the expression when a bound figure exists.
- "estimated_result" is your best guess; it will be checked independently."""


class Analyst:
    def __init__(self, backend: LLMBackend, config: Optional[GenerationConfig] = None):
        self.backend = backend
        self.config = config or GenerationConfig()

    def run(self, record: PipelineRecord) -> Optional[Derivation]:
        catalogue = "\n".join(
            f"- {f.id}: {f.label} = {f.value} {f.unit} ({f.period or 'no period'})"
            for f in record.figures
        )
        user = (
            f"Question: {record.question}\n\n"
            f"Available figures:\n{catalogue or '(none extracted)'}\n\n"
            "Plan the calculation."
        )
        try:
            payload = self.backend.chat_json(ANALYST_SYSTEM, user, self.config)
            return Derivation(
                expression=str(payload["expression"]),
                bindings={str(k): str(v) for k, v in payload.get("bindings", {}).items()},
                claimed_result=float(payload["estimated_result"]),
                operation_label=str(payload.get("operation_label", "")),
            )
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("Analyst failed for %s: %s", record.question_id, exc)
            return None


# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------

WRITER_SYSTEM = """You write a short factual answer to a financial question.

You are given a verified numeric result. State it plainly, in one or two
sentences. Do not introduce any number that was not given to you. Do not round
beyond two decimal places. Do not hedge."""


class Writer:
    def __init__(self, backend: LLMBackend, config: Optional[GenerationConfig] = None):
        self.backend = backend
        self.config = config or GenerationConfig()

    def run(self, record: PipelineRecord, value: Optional[float]) -> str:
        if value is None:
            return "The answer could not be determined from the source document."
        user = (
            f"Question: {record.question}\n"
            f"Verified result: {value}\n"
            "Write the answer."
        )
        return self.backend.chat(WRITER_SYSTEM, user, self.config).strip()


def claim_from_derivation(derivation: Derivation, value: float, unit: str = "USD") -> NumericClaim:
    """Wrap a computed result as an auditable claim."""
    return NumericClaim(
        value=value,
        surface_text=f"{derivation.operation_label or 'result'}: {value}",
        derivation=derivation,
        figure_ids=list(derivation.bindings.values()),
        unit=unit,
    )
