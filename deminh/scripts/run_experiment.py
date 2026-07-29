#!/usr/bin/env python3
"""Run the three-arm DeMiNH experiment.

Examples
--------
Smoke test with no model and no data (checks the plumbing only):
    python scripts/run_experiment.py --backend mock --dataset synthetic --limit 20

Real run against a local 8B model:
    python scripts/run_experiment.py \
        --backend ollama --model llama3.1:8b-instruct-q4_K_M \
        --dataset finqa --data-path data/finqa_test.json \
        --limit 200 --out results/run_001

Always pass --out with a distinct name per run and commit the resulting
summary.json. Reproducibility is one of the six BCS outcomes you are being
marked against, and "I overwrote the results" is not a defence.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deminh.data import load_finqa, load_tatqa, synthetic_records
from deminh.experiment import Experiment, ExperimentConfig
from deminh.graph import Configuration
from deminh.injection import ErrorCategory, InjectionConfig
from deminh.llm import MockBackend, OllamaBackend, OpenAICompatBackend


def build_backend(args):
    if args.backend == "ollama":
        return OllamaBackend(model=args.model, host=args.host)
    if args.backend == "openai":
        return OpenAICompatBackend(model=args.model, base_url=args.host)
    return MockBackend(default=json.dumps({
        "figures": [], "expression": "0", "bindings": {}, "estimated_result": 0.0
    }))


def load_records(args):
    if args.dataset == "finqa":
        return load_finqa(args.data_path, limit=args.limit)
    if args.dataset == "tatqa":
        return load_tatqa(args.data_path, limit=args.limit)
    return synthetic_records(n=args.limit or 20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["ollama", "openai", "mock"], default="mock")
    parser.add_argument("--model", default="llama3.1:8b-instruct-q4_K_M")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--dataset", choices=["finqa", "tatqa", "synthetic"],
                        default="synthetic")
    parser.add_argument("--data-path", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--injection-rate", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--no-langgraph", action="store_true")
    parser.add_argument("--out", default="results/latest")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.dataset != "synthetic" and not args.data_path:
        parser.error("--data-path is required for finqa and tatqa")

    records = load_records(args)
    logging.info("Loaded %d records from %s", len(records), args.dataset)

    experiment = Experiment(
        backend=build_backend(args),
        config=ExperimentConfig(
            injection=InjectionConfig(
                categories=list(ErrorCategory),
                rate=args.injection_rate,
                seed=args.seed,
            ),
            arms=list(Configuration),
            use_langgraph=not args.no_langgraph,
            output_dir=args.out,
        ),
    )

    results = experiment.run(records)
    summary = experiment.summarise(results)
    out = experiment.save(results, summary)

    print(json.dumps(summary, indent=2))
    print(f"\nWritten to {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
