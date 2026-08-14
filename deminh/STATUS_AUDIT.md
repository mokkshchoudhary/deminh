# DeMiNH — Repository Status Audit

**Date:** 2026-08-14
**Scope:** read-only audit. No files in the repository were modified.
**Repo:** `g:\deminh` — branch `main`, HEAD `d108453`

---

## 1. Structure

Repository root holds two things: the vendored upstream FinQA repository
(including its real dataset) and the project package under `deminh/`.

| Path | What it is |
|---|---|
| `deminh/src/deminh/schemas.py` | Dataclasses: `Provenance`, `Figure`, `Derivation`, `NumericClaim`, `Mechanism`/`Severity` enums, `Flag`, `VerificationReport`, `PipelineRecord`, `InjectionRecord` |
| `deminh/src/deminh/numeric.py` | Financial number parse/compare: comma grouping, `(1,234)` negatives, scale words, `close_enough`, `same_up_to_scale`, `appears_in`, `normalise_label` |
| `deminh/src/deminh/llm.py` | `LLMBackend` ABC + `OllamaBackend` / `OpenAICompatBackend` / `MockBackend`, `GenerationConfig` (temp 0.0, top_p 1.0, seed 42), `extract_json` |
| `deminh/src/deminh/agents.py` | Extractor / Analyst / Writer + their shared system prompts, `claim_from_derivation` |
| `deminh/src/deminh/graph.py` | `Configuration` enum, `Pipeline` nodes, `run_sequential`, `build_graph` (LangGraph), `verifier_config_for` |
| `deminh/src/deminh/injection.py` | `ErrorCategory` (6), `InjectionHarness`, `EXPECTED_CATCHER` |
| `deminh/src/deminh/metrics.py` | `ConfusionMatrix`, `detection_by_category`, `detection_by_mechanism`, `MitigationMetrics`, `mcnemar`, `bootstrap_ci` |
| `deminh/src/deminh/experiment.py` | Three-arm paired runner, `_generate_once` deep-copy (I1), summariser, save |
| `deminh/src/deminh/data.py` | `load_finqa` (supports `offset`), `load_tatqa`, `synthetic_records` |
| `deminh/src/deminh/verification/recompute.py` | AST-based `safe_eval` + claim check + repair proposal |
| `deminh/src/deminh/verification/provenance.py` | Source-span grounding. Detects only |
| `deminh/src/deminh/verification/identities.py` | Accounting identities, synonym index, `measure_coverage()` |
| `deminh/src/deminh/verification/selfcheck.py` | Arm 2's model-based verifier |
| `deminh/src/deminh/verification/orchestrator.py` | Mechanism sequencing, `RepairPolicy`, repair application |
| `deminh/scripts/run_experiment.py` | CLI |
| `deminh/scripts/measure_coverage.py` | FR5 coverage measurement (currently untracked) |
| `deminh/tests/` | 44 tests across 7 files |
| `deminh/results/` | 4 pilots + `run_001` + `run_002` + `fr5_coverage.json` |
| `FinQA/` | Upstream FinQA repo, including `dataset/*.json` (~107 MB of real data) |

Source line counts total 3090 across `src/`, `scripts/`, `tests/`.

---

## 2. Tests

**44 passed, 0 failed.**

```
python -m pytest tests -q --basetemp=<writable dir>
44 passed in 0.39s
```

The default invocation produces **1 ERROR**, which is an environment fault, not a
code fault:

```
ERROR tests/test_pipeline.py::test_full_experiment_produces_a_summary
PermissionError: [WinError 5] Access is denied:
  'C:\Users\moksh\AppData\Local\Temp\pytest-of-moksh'
```

pytest's `tmp_path` fixture cannot write to the default Windows temp directory.
Pass `--basetemp` to a writable path, or fix the ACL on that directory. Nothing
in DeMiNH is broken by it.

Invariant I4 is covered and passing:
`test_deterministic_arm_makes_no_model_calls_during_verification`.

---

## 3. Implemented vs stubbed

| Component | State | Note |
|---|---|---|
| Typed schemas | **DONE** | 8 dataclasses + 2 enums, id generation, `coverage()`, lookup helpers |
| Financial number parsing | **DONE** | 7 public functions, 7 tests |
| LLM backends | **DONE** | Ollama / OpenAI-compatible / Mock all real; `extract_json` raises loudly rather than returning `{}` |
| Extractor / Analyst / Writer | **DONE** | Prompts shared across arms (I2 held); Analyst returns an expression, not a finished number (I5 held) |
| LangGraph wiring | **PARTIAL** | See note below |
| Error injection harness | **DONE** | 6 categories, all wired, all tested |
| Detection metrics | **DONE** | precision / recall / F1 / FPR, plus per-category and per-mechanism breakdowns |
| Mitigation metrics | **DONE** | accuracy before/after, repaired, harmed, repair rate, harm rate, percent-aware gold matching |
| Three-arm experiment runner | **DONE** | I1 deep-copy confirmed, balanced round-robin category assignment, McNemar in the summary |
| FinQA loader | **DONE** | Verified against the real files — see §4 |
| TAT-QA loader | **PARTIAL** | Code complete but never run against real data; field-name assumptions unverified |
| CLI | **DONE** | All arguments wired except `--no-langgraph`, which is inert |

### LangGraph — why PARTIAL

Three separate problems, all pointing the same way:

1. `langgraph` is **not installed** in the active environment
   (`ModuleNotFoundError: No module named 'langgraph'`), despite being listed in
   `requirements.txt`.
2. `experiment.py::Experiment.run` never calls `Pipeline.run()` or
   `Pipeline.build_graph()`. It invokes `node_extract`, `node_analyse`,
   `node_verify` and `node_write` directly.
3. `ExperimentConfig.use_langgraph` is set by the CLI's `--no-langgraph` flag and
   is then **never read anywhere**.

Consequence: every result currently on disk was produced by the sequential path.
The compiled-graph path is untested at experiment scale. This does not invalidate
anything — CLAUDE.md §8 requires `run_sequential` to be behaviourally identical —
but the dissertation should not claim the graph executed the runs.

### Error injection — all six categories confirmed

| # | Category | What it injects |
|---|---|---|
| 1 | `arithmetic_slip` | Perturbs the claim value by ±15% relative. Right inputs, right operation, wrong sum. |
| 2 | `wrong_extraction` | Overwrites one figure's value *and* provenance with another real figure's. The number stays genuine and traceable; only the mapping is wrong. |
| 3 | `wrong_operation` | Swaps the first `+`, `-`, `*` or `/` in the Analyst's expression, then **re-evaluates** so the reported value follows the corrupted plan. Deliberately invisible to recomputation. |
| 4 | `invented_figure` | Appends a fabricated `Figure` (random value 1e3–1e7) with fake provenance, attaches it to the claim, and sets the claim value to it. |
| 5 | `scale_error` | Multiplies a randomly chosen figure's value by 1e3, 1e-3, 1e6 or 1e-6. Thousands read as millions. |
| 6 | `sign_error` | Negates a randomly chosen non-zero figure. Parenthesised negative read as positive. |

Categories 5 and 6 both operate on **figures** rather than claims, so both
propagate to claims via `affected_claim_ids`.

---

## 4. Data

### FinQA — present and loadable

Located at `FinQA/dataset/`, **not** at `deminh/data/`.

| File | Raw items | Loaded records | With gold answer |
|---|---|---|---|
| `test.json` | 1147 | 1147 | 1127 |
| `dev.json` | 883 | 883 | 873 |
| `train.json` | 6251 | 6251 | 6127 |
| `private_test.json` | 919 | 919 | 0 (held out — expected) |

`load_finqa` parses all four without error.

### TAT-QA — not downloaded

```
glob **/*tat*.json          →  no matches
deminh/data/                →  empty
load_tatqa(...)             →  FileNotFoundError
```

The synthetic fallback works (20 records generated).

Also note: `deminh/data/` being empty means the CC BY licence copy required by
CLAUDE.md §11 is not in place.

---

## 5. Results so far

A full three-arm experiment has been run end to end **six times** against real
FinQA with a live Ollama model. CLAUDE.md §12's "Not done" list is **stale** —
items 1, 2, 3, 5 and 6 are complete.

| Run | n per arm | Model | Slice |
|---|---|---|---|
| `pilot_qwen35_4b_synth5` | 5 | qwen3.5:4b | synthetic |
| `pilot_finqa_qwen35_4b_5` | 5 | qwen3.5:4b | finqa 0–4 |
| `pilot_finqa_qwen35_4b_5_v2` | 5 | qwen3.5:4b | finqa 0–4 (re-run) |
| `pilot_finqa_qwen35_4b_50` | 44 | qwen3.5:4b | finqa, limit 50 |
| **`run_001`** | **180** | qwen3.5:4b | `test.json` 0–199 |
| **`run_002`** | **309** | qwen3.5:4b | `test.json` 200–549 (offset) |

Each directory contains `summary.json`, `records_no_verifier.json`,
`records_self_check.json`, `records_deminh.json`, and a sibling `.log`.

### run_001 — n=180 per arm, 72 corrupted

| Arm | precision | recall | FPR | acc before | acc after | delta | repair rate | harm rate |
|---|---|---|---|---|---|---|---|---|
| `no_verifier` | 0.0 | 0.0 | 0.0 | 0.3103 | 0.3103 | 0.0 | – | – |
| `self_check` | 0.4182 | 0.9583 | 0.8889 | 0.3103 | 0.3506 | +4.02pp | 0.0833 | 0.0556 |
| `deminh` | 0.4444 | 1.0 | 0.8333 | 0.3103 | 0.3908 | +8.05pp | 0.2250 | 0.2407 |

McNemar: n_discordant = 27, chi2 = 2.3704, **p = 0.1237** (not significant).

### run_002 — n=309 per arm, 123 corrupted

| Arm | precision | recall | FPR | acc before | acc after | delta | repair rate | harm rate |
|---|---|---|---|---|---|---|---|---|
| `no_verifier` | 0.0 | 0.0 | 0.0 | 0.318 | 0.318 | 0.0 | – | – |
| `self_check` | 0.419 | 0.9675 | 0.8871 | 0.318 | 0.3475 | +2.95pp | 0.0817 | 0.0825 |
| `deminh` | 0.4485 | 0.9919 | 0.8065 | 0.318 | 0.3344 | **+1.64pp** | 0.1202 | **0.2062** |

McNemar: n_discordant = 42, chi2 = 6.881, **p = 0.0087** (significant at 0.05).
deminh right / self wrong = 30; the reverse = 12.

### Pooled run_001 + run_002 (n = 489, disjoint slices)

Hand-computed in `RUN_LOG.md`, not produced by code.

b = 48, c = 21, n_discordant = 69, chi2 = 9.797, **p = 0.00175**.

This is the strongest statement the data currently supports.

### FR5 — identity coverage

`deminh/results/fr5_coverage.json`:

```json
{
  "coverage_balance_sheet": 0.0,
  "coverage_gross_profit": 0.0,
  "coverage_operating_income": 0.0,
  "coverage_any": 0.0,
  "n_records": 50,
  "n_extract_failed": 0
}
```

**Identity mechanism coverage is 0%** across 50 real FinQA records, with zero
extraction failures — so this is a real measurement, not an artefact. Consistent
with `flags_by_mechanism` in every run, where `identities` never appears and all
deminh flags come from `provenance` and `recompute`. Investigated by hand; no bug
found. The cause is structural: FinQA questions are narrowly scoped, so the
Extractor returns 1–3 figures rather than a full statement section, and an
identity needs all of its components co-extracted.

### Other measured facts already on disk

- **Parse-failure rate:** 10% (run_001), 11.7% (run_002) — consistent.
- **Category applicability** (run_002 log, 84 logged failures):
  - 69 are `wrong_operation` — roughly a 97% non-applicability rate. Most FinQA
    claims are direct single-figure lookups with no operator to corrupt. This
    leaves n=2 in run_002 and n=0 in run_001.
  - 15 are `wrong_extraction` — roughly 44%, needing two figures with different
    values in the same extraction.

`deminh/RUN_LOG.md` is thorough and honest. It records the mid-run Ollama outage
and its cause, marks the pilot accuracy figures as unrepresentative and not to be
quoted, and states the mitigation-delta reversal between runs plainly rather than
smoothing it.

---

## 6. TODO / FIXME / XXX / TBD

**Zero hits** across `src/`, `scripts/`, `tests/`, `*.md`, `*.yaml` and `*.txt`.

The nearest equivalent is a prose prompt in `identities.py:76`:

```python
# ADD YOUR OWN HERE. Candidates worth considering: working capital,
# current ratio consistency, retained earnings roll-forward,
# EPS = net income / weighted average shares.
```

Open items are tracked in prose instead — CLAUDE.md §6 lists five open decisions,
and `RUN_LOG.md` ends with a "Still open" note on harm-rate instability.

---

## 7. Verdict

The shortest path to a full three-arm run producing detection and mitigation
numbers is **zero steps — it has already happened twice** (run_001 at n=180,
run_002 at n=309), on real FinQA with a live model, yielding a significant pooled
McNemar result (p = 0.00175, n = 489). CLAUDE.md §12 badly understates the
current position and should be brought up to date. What genuinely remains is one
further disjoint batch (`--offset 550`), because `RUN_LOG.md` flags harm rate as
still trending upward with n (0.20 → 0.21) rather than converging — plus
committing run_002, which is presently untracked.

The single biggest blocker is not code. It is the **harm-rate / mitigation
contradiction**: deminh wins detection decisively, yet its net accuracy gain in
run_002 was *lower* than self_check's (+1.64pp vs +2.95pp), reversing run_001,
because `RECOMPUTE_ONLY` repairs harm roughly 2.5x more often proportionally.
That is a genuine finding, but a third batch is needed to establish whether the
reversal is stable or sampling noise, and it makes CLAUDE.md §6 item 3 — report
under two repair policies — the highest-value remaining work.

Two secondary blockers, both already measured, and both arguing for narrowing
scope rather than writing more code: identity coverage is 0%, so mechanism 3
contributes nothing on FinQA and cannot carry weight in the results chapter; and
`wrong_operation` is roughly 97% non-applicable, so that taxonomy row cannot be
reported at a usable n.

---

## Appendix — repository hygiene

Uncommitted at time of audit:

```
 M deminh/RUN_LOG.md                  (+131 lines: FR5, run_002, pooled analysis)
 M deminh/scripts/run_experiment.py   (+6/-2: --offset)
 M deminh/src/deminh/data.py          (+13/-2: offset support)
?? deminh/results/fr5_coverage.json
?? deminh/results/run_002.log
?? deminh/results/run_002/
?? deminh/scripts/measure_coverage.py
```

Per CLAUDE.md §4, `summary.json` for each run should be committed. `run_002` and
the FR5 result are both currently untracked.
