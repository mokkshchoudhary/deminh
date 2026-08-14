"""Dataset loading.

FinQA and TAT-QA are both distributed as JSON. The loaders below normalise them
into PipelineRecord objects. Field names in these datasets have shifted between
releases — inspect the actual file you download and adjust the key names rather
than assuming these are right.

LICENSING. Your proposal states both are CC BY 4.0 and that this permits
redistribution inside the submitted code zip. Confirm this with your supervisor
against the licence file that ships with the data you actually download, keep a
copy of that licence in `data/`, and attribute both datasets in your
acknowledgements. Your ethics guidance requires you to confirm permission
explicitly, and CC BY specifically requires attribution.

A synthetic generator is included so the pipeline can be exercised before the
datasets are in place. Synthetic data is for plumbing only — no result in the
dissertation should rest on it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from .numeric import parse_number
from .schemas import PipelineRecord

log = logging.getLogger(__name__)


def load_finqa(path: str | Path, limit: Optional[int] = None,
                offset: int = 0) -> list[PipelineRecord]:
    """Load FinQA. Each item has pre_text, post_text, a table, and a qa block.

    `offset` skips the first N items in the file before collecting `limit`
    records. Decoding is pinned (I3), so re-running the same slice of the
    dataset reproduces identical output — offset lets a follow-up run cover
    fresh items instead of repeating work already on disk from a prior run.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))[offset:]
    records: list[PipelineRecord] = []

    for i, item in enumerate(payload):
        if limit is not None and len(records) >= limit:
            break
        qa = item.get("qa") or {}
        question = qa.get("question")
        if not question:
            continue

        context = "\n".join([
            " ".join(item.get("pre_text", [])),
            _render_table(item.get("table", [])),
            " ".join(item.get("post_text", [])),
        ]).strip()

        records.append(PipelineRecord(
            question_id=str(item.get("id", f"finqa_{i}")),
            question=question,
            context=context,
            gold_answer=parse_number(str(qa.get("exe_ans", qa.get("answer", "")))),
            meta={
                "dataset": "finqa",
                "gold_program": qa.get("program"),
                "gold_answer_raw": qa.get("answer"),
            },
        ))
    return records


def load_tatqa(path: str | Path, limit: Optional[int] = None) -> list[PipelineRecord]:
    """Load TAT-QA. Each item has a table plus paragraphs and several questions."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records: list[PipelineRecord] = []

    for i, item in enumerate(payload):
        table = (item.get("table") or {}).get("table", [])
        paragraphs = " ".join(p.get("text", "") for p in item.get("paragraphs", []))
        context = f"{_render_table(table)}\n\n{paragraphs}".strip()

        for j, qa in enumerate(item.get("questions", [])):
            if limit is not None and len(records) >= limit:
                return records
            answer = qa.get("answer")
            if isinstance(answer, list):
                answer = answer[0] if answer else None

            records.append(PipelineRecord(
                question_id=str(qa.get("uid", f"tatqa_{i}_{j}")),
                question=qa.get("question", ""),
                context=context,
                gold_answer=parse_number(str(answer)) if answer is not None else None,
                meta={
                    "dataset": "tatqa",
                    "answer_type": qa.get("answer_type"),
                    "scale": qa.get("scale"),
                },
            ))
    return records


def _render_table(table: Iterable[Iterable[Any]]) -> str:
    return "\n".join(" | ".join(str(cell) for cell in row) for row in table or [])


def synthetic_records(n: int = 20, seed: int = 3) -> list[PipelineRecord]:
    """Small, fully-controlled records for smoke-testing the plumbing."""
    import random

    rng = random.Random(seed)
    records = []
    for i in range(n):
        revenue = rng.randrange(50_000, 500_000)
        cogs = rng.randrange(10_000, revenue - 1_000)
        gross = revenue - cogs
        liabilities = rng.randrange(10_000, 200_000)
        equity = rng.randrange(10_000, 200_000)
        assets = liabilities + equity

        context = (
            "Consolidated statements (in thousands)\n"
            f"Revenue | {revenue:,}\n"
            f"Cost of sales | {cogs:,}\n"
            f"Gross profit | {gross:,}\n"
            f"Total liabilities | {liabilities:,}\n"
            f"Total shareholders equity | {equity:,}\n"
            f"Total assets | {assets:,}\n"
        )
        records.append(PipelineRecord(
            question_id=f"syn_{i}",
            question="What was the gross profit margin, as a percentage?",
            context=context,
            gold_answer=round(gross / revenue * 100, 4),
            meta={"dataset": "synthetic"},
        ))
    return records
