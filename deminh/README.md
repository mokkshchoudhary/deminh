# DeMiNH

Detecting and Mitigating Numerical Hallucinations in Multi-Agent LLM Systems for
Financial Research.

The system is the apparatus; the experiment is the contribution. The code exists
to answer one question: **does a verifier need to be independent of the model it
checks, or is a model checking its own work good enough?**

---

## Acknowledgement

This scaffold was produced with assistance from a generative AI system and must
be acknowledged as such in your dissertation, per your programme's academic
misconduct policy. That policy permits AI-assisted code provided the assistance
is referenced; passing it off unacknowledged does not. You will also need to be
able to explain every part of it in supervision, which is a good reason to read
it properly rather than run it.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q                     # 44 tests, no model needed
python scripts/run_experiment.py --backend mock --dataset synthetic --limit 20
```

Real run, once you have a model server and the datasets:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
python scripts/run_experiment.py \
  --backend ollama --model llama3.1:8b-instruct-q4_K_M \
  --dataset finqa --data-path data/finqa_test.json \
  --limit 200 --out results/run_001
```

---

## Architecture

```
                    ┌──────────┐   ┌─────────┐
   question ──────► │ Extractor│──►│ Analyst │──┐
   + document       └──────────┘   └─────────┘  │
                    figures with   expression,  │
                    provenance     not a result │
                                                ▼
                    ┌───────────────────────────────────────┐
                    │  VERIFICATION  (arm-dependent)        │
                    │                                       │
                    │  arm 1  no verifier                   │
                    │  arm 2  same model checks itself      │
                    │  arm 3  recompute + provenance        │
                    │         + accounting identities       │
                    └───────────────────┬───────────────────┘
                                        ▼
                                   ┌─────────┐
                                   │ Writer  │──► answer
                                   └─────────┘
```

The Analyst emits an *expression*, never a computed result. That single decision
is what makes deterministic verification possible: there is something to re-run.

### The three mechanisms and what each can reach

| Mechanism | Catches | Cannot catch | Can repair? |
|---|---|---|---|
| Recomputation | arithmetic slips | anything where the maths is right on the wrong input | yes |
| Provenance | invented figures, transcription and scale slips | a real number that is the wrong line item | no |
| Accounting identities | wrong line item, wrong operation | anything outside the encoded identities | no |

The mechanisms are not redundant, and the table above is the argument for why.
Verify it empirically rather than asserting it — `detection_by_category` in
`metrics.py` produces exactly this breakdown from your results.

### Why this is not VeNRA

VeNRA's independence comes from a *trained 3B model* auditing execution traces.
A trained model can share blind spots with the generator. Here, independence is
structural: recomputation, provenance and identity checks depend on no model's
judgement at all.

`test_pipeline.py::test_deterministic_arm_makes_no_model_calls_during_verification`
asserts this property in code. If that test ever fails, the claim is no longer
true of the implementation. Keep it.

---

## Layout

```
src/deminh/
  schemas.py                 typed figures, derivations, claims, flags
  numeric.py                 financial number parsing and tolerant comparison
  llm.py                     Ollama / OpenAI-compatible / mock backends
  agents.py                  Extractor, Analyst, Writer + prompts
  graph.py                   LangGraph wiring, the three configurations
  injection.py               error injection harness (ground truth generator)
  metrics.py                 detection, mitigation, McNemar, bootstrap CI
  experiment.py              the paired three-arm runner
  data.py                    FinQA / TAT-QA loaders, synthetic fallback
  verification/
    recompute.py             safe AST evaluator, deterministic recomputation
    provenance.py            source-span grounding
    identities.py            accounting identity cross-derivation + coverage
    selfcheck.py             the arm-2 baseline
    orchestrator.py          mechanism sequencing and repair policy
scripts/run_experiment.py
tests/                       44 tests, all runnable without a GPU
```

---

## Decisions still yours to make

These are deliberately unresolved. They are also the things you will be examined
on, so resolving them by argument rather than by default matters.

1. **The error taxonomy.** Six categories are proposed in `injection.py`. The
   categories you inject are the only ones you can report on. Justify the set,
   fix it before you build the test corpus, and do not revise it mid-experiment.
2. **The identity set.** `DEFAULT_IDENTITIES` has three entries. Run
   `identities.measure_coverage()` over a FinQA sample and report the number —
   this is the open FR5 item in your notes. If coverage is low, that bounds what
   the third mechanism can contribute, and saying so plainly is stronger than
   hoping nobody checks.
3. **The repair policy.** `RepairPolicy.RECOMPUTE_ONLY` is the conservative
   default. Aggressive repair raises your mitigation gain and your harm rate
   together. Consider reporting results under two policies.
4. **Prompts.** The ones in `agents.py` are functional starting points, not tuned
   artefacts. Tune them against your own model, version them, and hold them
   identical across all three arms.
5. **Natural vs injected errors.** Hand-label a small sample of errors the
   pipeline makes on its own and compare their category distribution to your
   injected one. This converts your main methodological limitation into analysis.

---

## Things that will bite you

- **Non-deterministic decoding.** `temperature=0.0` and a fixed seed are set by
  default. If you unpin them, the arms diverge and the comparison stops meaning
  anything.
- **Reporting recall alone.** A verifier that flags everything has perfect
  recall. Put false-positive rate and harm rate in the same table, at the same
  size.
- **The wrong significance test.** The arms run on the same items, so the
  comparison is paired. `metrics.mcnemar` is correct here; a two-sample
  proportion test is not. Report `n_discordant` — below roughly 25 the
  approximation is unreliable.
- **Unparseable model output.** Small quantised models return prose around their
  JSON constantly. `llm.extract_json` handles the common cases and raises
  loudly otherwise. Log the failures and report the parse-failure rate; silently
  treating them as "nothing found" corrupts your extraction numbers.
- **Dataset licensing.** Confirm the CC BY 4.0 terms against the licence file
  that actually ships with your download, keep a copy in `data/`, and attribute
  both datasets in your acknowledgements.

---

## Ethics

Data category **A**, participant category **0**: no data derived from humans or
animals, and no human participants in requirements analysis or evaluation. FinQA
and TAT-QA are built from public company filings, which are corporate rather
than personal data. If you later add any evaluation with human participants,
that becomes category 2 or 3 and the statement in your assessments must be
updated before the activity takes place.
