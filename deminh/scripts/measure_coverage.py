#!/usr/bin/env python3
"""Measure identity coverage on real data — open item FR5.

Runs the Extractor only (no Analyst, no verification, no injection) on a
sample of real records, then reports what fraction admit at least one
DEFAULT_IDENTITIES check via identities.measure_coverage(). This is the
number CLAUDE.md asks to report before relying on the identities mechanism
to carry any real weight in the results.

Example:
    python scripts/measure_coverage.py \
        --backend ollama --model qwen3.5:4b \
        --dataset finqa --data-path G:\\deminh\\FinQA\\dataset\\test.json \
        --limit 50 --offset 550 --out results/fr5_coverage.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deminh.data import load_finqa, load_tatqa, synthetic_records
from deminh.graph import Pipeline, Configuration
from deminh.llm import MockBackend, OllamaBackend, OpenAICompatBackend
from deminh.verification.identities import DEFAULT_IDENTITIES, measure_coverage


def build_backend(args):
    if args.backend == "ollama":
        return OllamaBackend(model=args.model, host=args.host)
    if args.backend == "openai":
        return OpenAICompatBackend(model=args.model, base_url=args.host)
    return MockBackend(default=json.dumps({"figures": []}))


def load_records(args):
    if args.dataset == "finqa":
        return load_finqa(args.data_path, limit=args.limit, offset=args.offset)
    if args.dataset == "tatqa":
        return load_tatqa(args.data_path, limit=args.limit)
    return synthetic_records(n=args.limit or 20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["ollama", "openai", "mock"], default="mock")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--dataset", choices=["finqa", "tatqa", "synthetic"], default="finqa")
    parser.add_argument("--data-path", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", default="results/fr5_coverage.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.dataset != "synthetic" and not args.data_path:
        parser.error("--data-path is required for finqa and tatqa")

    records = load_records(args)
    logging.info("Loaded %d records from %s (offset=%d)", len(records), args.dataset, args.offset)

    pipeline = Pipeline(build_backend(args), Configuration.NO_VERIFIER)
    n_extract_failed = 0
    for record in records:
        try:
            state = pipeline.node_extract({"record": record})
            record.figures = state["record"].figures
        except Exception as exc:
            n_extract_failed += 1
            logging.warning("Extraction failed for %s: %s", record.question_id, exc)

    result = measure_coverage(records, DEFAULT_IDENTITIES)
    result["n_records"] = len(records)
    result["n_extract_failed"] = n_extract_failed
    result["identity_names"] = [i.name for i in DEFAULT_IDENTITIES]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"\nWritten to {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
