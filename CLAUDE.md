# CLAUDE.md

Context for agentic sessions in this repository. Read fully before making changes.

---

## 1. What this project is

**DeMiNH** — Detecting and Mitigating Numerical Hallucinations in Multi-Agent LLM
Systems for Financial Research. MSc dissertation, University of Liverpool.

**The contribution is an experiment, not a system.** The three-agent pipeline is
apparatus. The dissertation's claim rests on one controlled comparison:

> Does a verifier need to be **independent of the model it checks**, or is a model
> checking its own work good enough?

Three arms, identical in every respect except the checker:

| Arm | Verifier | Role |
|---|---|---|
| `no_verifier` | none | floor |
| `self_check` | same 8B model checks its own answer | the common, cheap approach |
| `deminh` | deterministic code: recomputation, provenance, accounting identities | the proposal |

If a change makes the pipeline better but weakens the comparison, **the change is
wrong**. Optimise the experiment, not the artefact.

---

## 2. Invariants — do not break these

These are the failure modes that silently invalidate the dissertation. Each is
cheap to violate and expensive to discover late.

**I1. One generation pass, deep-copied into the arms.**
`experiment.py::_generate_once` runs Extractor and Analyst once per question; the
result is deep-copied per arm. Re-generating per arm would let generation
variance masquerade as verifier quality. Never "fix" this by giving each arm its
own generation.

**I2. Prompts are identical across arms.**
`agents.py` prompts are shared. Never tune a prompt for one arm. If a prompt
changes, it changes for all three and every prior result is invalidated — say so
in the run log rather than quietly re-running.

**I3. Decoding is pinned.**
`GenerationConfig` defaults to `temperature=0.0`, `top_p=1.0`, `seed=42`. Do not
unpin for "better" output. Non-determinism across arms destroys pairing.

**I4. The deterministic verifier never calls a model.**
Enforced by
`tests/test_pipeline.py::test_deterministic_arm_makes_no_model_calls_during_verification`.
This test *is* the independence claim in executable form. Never delete it, never
mark it xfail, never add an LLM call inside `verification/recompute.py`,
`provenance.py`, `identities.py`, or `orchestrator.py`.

**I5. The Analyst emits an expression, never a computed result.**
This is what makes deterministic re-derivation possible. If the Analyst starts
returning finished numbers, recomputation has nothing to re-run and arm 3
collapses into arm 2.

**I6. The self-check baseline is implemented fairly.**
Same model, same seed, same information (document, figures, derivation), same
output contract. A weakened baseline makes the headline result worthless and an
examiner will say so. If you improve arm 3's information access, give arm 2 the
same access.

**I7. The error taxonomy is frozen once the corpus is built.**
The categories injected are the only ones reportable. Changing them mid-study
means re-running everything. If a change is genuinely needed, re-run all arms and
note it.

---

## 3. Repository map

```
src/deminh/
  schemas.py        Figure, Provenance, Derivation, NumericClaim, Flag,
                    VerificationReport, PipelineRecord, InjectionRecord.
                    Numbers travel as structured objects carrying their origin —
                    never as bare floats in prose. Change here ripples everywhere.
  numeric.py        Financial number parsing: comma grouping, (1,234) negatives,
                    scale words, tolerant comparison, scale-factor detection.
                    Dull and load-bearing. Most false positives originate here.
  llm.py            Backends: OllamaBackend (the real one), OpenAICompatBackend,
                    MockBackend. Plus extract_json, which handles the prose-and-
                    code-fence wrapping small quantised models produce.
  agents.py         Extractor / Analyst / Writer + their prompts. See I2.
  graph.py          Configuration enum, Pipeline, LangGraph wiring,
                    run_sequential fallback (no langgraph dependency).
  injection.py      ErrorCategory (6), InjectionHarness, EXPECTED_CATCHER.
                    The ground-truth generator. See I7.
  metrics.py        ConfusionMatrix, detection_by_category, MitigationMetrics
                    (incl. harm rate), mcnemar, bootstrap_ci.
  experiment.py     The paired three-arm runner and summariser. See I1.
  data.py           FinQA / TAT-QA loaders + synthetic_records fallback.
  verification/
    recompute.py    safe_eval (AST-based, no eval()) + claim checking. Repairs.
    provenance.py   Source-span grounding. Detects; cannot repair.
    identities.py   Accounting identities + measure_coverage(). Detects only.
    selfcheck.py    Arm 2's verifier. The comparison target.
    orchestrator.py Mechanism sequencing + RepairPolicy.
scripts/run_experiment.py   CLI
tests/                      44 tests, all runnable with no GPU and no datasets
```

---

## 4. Commands

```bash
python -m pytest tests -q                    # full suite, ~0.2s, no model needed
python -m pytest tests/test_pipeline.py -q   # integration / wiring only

# Plumbing smoke test — no model, no data
python scripts/run_experiment.py --backend mock --dataset synthetic --limit 20

# Real run
python scripts/run_experiment.py \
  --backend ollama --model llama3.1:8b-instruct-q4_K_M \
  --dataset finqa --data-path data/finqa_test.json \
  --limit 200 --out results/run_001
```

Always pass a distinct `--out` per run and commit `summary.json`. Overwriting
results is not recoverable and reproducibility is one of the six BCS outcomes
being marked.

---

## 5. What each mechanism can and cannot reach

Do not treat the mechanisms as interchangeable. They are not redundant, and the
argument for keeping all three is exactly that each covers what the others miss.

| Mechanism | Catches | Blind to | Repairs? |
|---|---|---|---|
| Recomputation | arithmetic slips | correct maths on the wrong input | **yes** |
| Provenance | invented figures, transcription/scale slips | a real number that is the wrong line item | no |
| Identities | wrong line item, wrong operation | anything outside the encoded identity set | no |

`injection.EXPECTED_CATCHER` records these as **pre-registered predictions**. When
results contradict it, that is a finding to investigate and report — not a bug to
paper over by adjusting the prediction after the fact.

Detection rate and repair rate are different quantities. Two of three mechanisms
detect without being able to repair. Tabulate them separately.

---

## 6. Open decisions — ask, do not guess

These are unresolved by design and are what the student is examined on. If a task
requires one of them, **surface the choice and its trade-off rather than picking
silently**.

1. **Error taxonomy** (`injection.py`). Six categories proposed. Must be justified
   and frozen before the corpus is built.
2. **Identity set** (`identities.py::DEFAULT_IDENTITIES`). Three entries. Run
   `measure_coverage()` on a real FinQA sample and report the number — this is
   open item FR5. Low coverage is a finding to state plainly, not a flaw to hide.
3. **Repair policy** (`orchestrator.py::RepairPolicy`). `RECOMPUTE_ONLY` is the
   conservative default. Aggressive repair raises mitigation gain and harm rate
   together. Consider reporting under two policies.
4. **Prompts** (`agents.py`). Functional starting points, not tuned artefacts.
5. **Second-model comparison** (FR10, Qwen3 14B) — whether independence-by-
   different-model runs as a secondary arm. Not implemented. Adding it means a
   fourth arm, not a modification of arm 3.

---

## 7. Traps

**Do not conflate this with VeNRA.** VeNRA (Agand, 2026, arXiv:2603.04663) gets
independence from a *trained 3B model* auditing execution traces. DeMiNH's
independence is structural — no model's judgement is involved. Never describe arm
3 as "a smaller model verifies". That describes VeNRA and forfeits the
originality claim. VeNRA also *detects* without recomputing a corrected value;
DeMiNH's recomputation mechanism repairs.

**Do not benchmark against VeNRA's published scores.** Different hardware, model
and setup. The comparison stays inside the controlled three-arm design.

**Do not report recall alone.** A verifier that flags everything has perfect
recall and is useless. False-positive rate and harm rate belong in the same table
at the same prominence.

**Do not use an unpaired significance test.** The arms run on the same items.
`metrics.mcnemar` is correct; a two-sample proportion test is not. Always report
`n_discordant` — below roughly 25 the chi-square approximation is unreliable.

**Do not let "LLMs are bad at arithmetic" become the finding.** That is settled
(PAL, Gao et al.; Program of Thoughts, Chen et al.) and this project builds on it
at the *generation* stage. The open question is about *checking*, and about error
types recomputation cannot reach — wrong extraction, invented figures. The
per-category breakdown is what separates a contribution from a restatement.

**Do not silently swallow parse failures.** `extract_json` raises on malformed
output. An empty parse looks identical to "the model found no figures" and would
corrupt extraction numbers. Log failures and report the parse-failure rate.

---

## 8. Conventions

- Python 3.11+, `from __future__ import annotations`, type hints throughout.
- Dataclasses for data, plain classes for behaviour. No frameworks beyond
  LangGraph.
- `eval()` is banned. Model-authored expressions go through
  `recompute.safe_eval`, which is AST-based and allow-lists operators.
- New verification mechanism → new module in `verification/`, a `Mechanism` enum
  member, wiring in `orchestrator.py`, an entry in `EXPECTED_CATCHER`, and tests.
- Every behavioural change needs a test. The suite runs in under a second; there
  is no excuse for skipping it.
- Docstrings explain **why**, especially where a choice is methodologically
  load-bearing. This code is submitted and read by markers.
- Keep `run_sequential` behaviourally identical to the compiled graph. It is the
  debugging path on hardware that cannot hold the model.

---

## 9. Hardware reality

6GB VRAM / 32GB RAM. An 8B model at 4-bit via an Ollama server, not in-process.
Generation dominates runtime, which is why I1 exists — one generation pass instead
of three is roughly a third off the dominant cost. Arm 2 still calls the model
during verification, so it is not free. Before proposing anything that multiplies
model calls, estimate the wall-clock cost against the timetable.

---

## 10. Assessment context

- **CA1** — specification and design proposal (15%). **Submitted.** Do not
  contradict it: agents are named **Extractor, Analyst, Writer**; the verification
  *mechanisms* are separate from the three named agents. Ethics stated as data
  category **A**, participant category **0**.
- **Remaining** — implementation, video/demo, dissertation.

BCS accreditation requires six outcomes; the ones this code touches most directly
are originality in application of knowledge, sound judgement under incomplete
data, self-direction, and critical self-evaluation. Honest reporting of negative
or partial results serves these better than a flattering result does. **If
independence does not beat self-checking, that is a valid and publishable
finding** — a cheaper design being sufficient is real evidence. Do not tune the
experiment toward a preferred outcome.

Referencing style: Harvard or IEEE, **to be confirmed with the supervisor**. Pick
one and apply it consistently once confirmed.

---

## 11. Academic integrity

This scaffold was AI-assisted and **must be acknowledged** in the dissertation.
University policy permits AI-assisted code when referenced; passing it off
unacknowledged is misconduct. The student must be able to explain any part of
this codebase in supervision — when generating code here, prefer clarity over
cleverness, and explain non-obvious choices in comments rather than leaving them
to be reverse-engineered under questioning.

Datasets: FinQA and TAT-QA, both understood to be CC BY 4.0. Confirm against the
licence file shipping with the actual download, keep a copy in `data/`, and
attribute both in the acknowledgements.

---

## 12. Where things stand

**Done.** Schemas, numeric parsing, three agents, three deterministic mechanisms,
self-check baseline, injection harness (6 categories), detection and mitigation
metrics, McNemar, paired three-arm runner, CLI, 44 tests. Runs end to end on the
synthetic dataset with a mock backend.

**Not done, roughly in order.**

1. Download FinQA and TAT-QA; verify the loaders against the real field names —
   these have shifted between releases and `data.py` assumes one layout.
2. Stand up the Ollama server; confirm the 8B 4-bit model returns parseable JSON
   under the current prompts. Measure and record the parse-failure rate before
   tuning anything.
3. Run `identities.measure_coverage()` on a FinQA sample. Report the number.
   This gates how much weight the identity mechanism can carry (open item FR5).
4. Freeze the error taxonomy with supervisor sign-off, then build the test corpus.
5. Pilot run at `--limit 50` to sanity-check runtime and metric shapes before
   committing to the full run.
6. Full run; commit `summary.json` and per-arm record dumps.
7. Hand-label a sample of *natural* pipeline errors and compare their category
   distribution against the injected distribution. This addresses the main
   methodological limitation — injected errors are a proxy — and converts it into
   analysis rather than a caveat.
8. Optional fourth arm: independence-by-different-model (FR10, Qwen3 14B).

**Before any full run, check:** tests pass, decoding is pinned, prompts are
unchanged since the last run or the change is logged, `--out` is a fresh path.
