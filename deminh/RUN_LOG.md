# Run log

One entry per experiment run. Append, never edit past entries — if a run was
wrong, say so in a new entry rather than rewriting history. Per CLAUDE.md I2/I7:
any change to prompts or the error taxonomy must be noted here, and everything
before that note is invalidated by it.

Numbers: precision/recall/FPR are detection metrics (flag raised vs. injection
ground truth). acc_before/after and repair/harm rate are mitigation metrics.
These are different quantities — don't average them.

---

## pilot_finqa_qwen35_4b_5

- Date: pre-2026-08-07 (exact date not recorded)
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0
- Dataset: finqa, n=5 loaded, 5 usable, 2 injected corruptions
- Purpose: first live-model smoke test on real FinQA data

| Arm | precision | recall | FPR | acc_before | acc_after | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.40 | 0.40 | - | - |
| self_check | 0.50 | 1.0 | 0.667 | 0.40 | 0.20 | 0.0 | 0.50 |
| deminh | 0.40 | 1.0 | 1.0 | 0.40 | 0.40 | 0.0 | 0.0 |

McNemar: n_discordant=1 (self_right_deminh_wrong=1). Far below the ~25 threshold
— not interpretable, sample too small by design (smoke test only).

---

## pilot_finqa_qwen35_4b_5_v2

- Date: pre-2026-08-07 (exact date not recorded)
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0
- Dataset: finqa, n=5 loaded, 5 usable, 2 injected corruptions
- Purpose: re-run of the 5-record smoke test (v2 — reason for re-run not logged
  at the time; going forward, note *why* a run is repeated here)

| Arm | precision | recall | FPR | acc_before | acc_after | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.20 | 0.20 | - | - |
| self_check | 0.40 | 1.0 | 1.0 | 0.20 | 0.20 | 0.0 | 0.0 |
| deminh | 0.50 | 1.0 | 0.667 | 0.20 | 0.40 | 0.25 | 0.0 |

McNemar: n_discordant=1 (deminh_right_self_wrong=1). Not interpretable at n=5.

---

## pilot_qwen35_4b_synth5

- Date: pre-2026-08-07 (exact date not recorded)
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0
- Dataset: synthetic, n=5, 2 injected corruptions
- Purpose: sanity check against synthetic data (per CLAUDE.md: plumbing only,
  no dissertation result should rest on this row)

| Arm | precision | recall | FPR | acc_before | acc_after | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.60 | 0.60 | - | - |
| self_check | 0.50 | 0.50 | 0.333 | 0.60 | 0.80 | 0.50 | 0.0 |
| deminh | 0.40 | 1.0 | 1.0 | 0.60 | 0.60 | 0.0 | 0.0 |

McNemar: n_discordant=3. Not interpretable at n=5.

---

## pilot_finqa_qwen35_4b_50

- Date: pre-2026-08-07 (exact date not recorded)
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0
- Dataset: finqa, n=50 loaded, 44 usable (6 dropped, empty question or failed
  generation), 19 injected corruptions
- Purpose: first larger pilot, still below McNemar's reliable threshold

| Arm | precision | recall | FPR | acc_before | acc_after | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.1136 | 0.1136 | - | - |
| self_check | 0.4524 | 1.0 | **0.92** | 0.1136 | 0.1364 | 0.0256 | 0.0 |
| deminh | 0.4524 | 1.0 | **0.92** | 0.1136 | 0.1364 | 0.0513 | 0.20 |

McNemar: n_discordant=4 (2 each direction) → p=1.0, **not interpretable**
(need ~25+ discordant pairs per CLAUDE.md).

**Notable:** self_check FPR=0.92 — flags almost every record regardless of
whether it was corrupted. Matches the "flags everything = useless verifier"
failure mode CLAUDE.md warns about. deminh has the *same* precision/recall/FPR
here (coincidence at this n, or provenance mechanism over-triggering — needs
checking once n=200 lands) but a higher repair_rate and a non-zero harm_rate
(0.20 — 1 of 5 repair attempts made things worse). Base model accuracy on raw
FinQA is very low (11.4%) before any verification — worth stating plainly in
the dissertation as a property of the 4B model, not the pipeline.

---

## run_001

- Date: 2026-08-07
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0, top_p 1.0
- Dataset: finqa, `FinQA/dataset/test.json` (1147 total records), limit 200
- Prompts: unchanged since pilot_finqa_qwen35_4b_50 (I2 — no re-run needed on
  that account)
- Error taxonomy: unchanged, 6 categories (I7)
- Purpose: get past the ~25 discordant-pair threshold so McNemar on
  deminh_vs_self_check is actually readable; first run with FPR checked at
  a size that isn't noise
- Status: **complete**. 200 loaded, 20 skipped (Analyst produced no parseable
  claim) → **parse-failure rate 10%** (this is the number CLAUDE.md "not done"
  item 2 asks for — recorded, not yet tuned against). 180 records per arm,
  72 corrupted, 6 of those excluded from mitigation calc for missing gold answer.

| Arm | precision | recall | FPR | acc_before | acc_after | delta | repaired | harmed | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.3103 | 0.3103 | 0.0 | - | - | - | - |
| self_check | 0.4182 | 0.9583 | **0.8889** | 0.3103 | 0.3506 | +0.0402 | 10 | 3 | 0.0833 | 0.0556 |
| deminh | 0.4444 | 1.0 | **0.8333** | 0.3103 | 0.3908 | +0.0805 | 27 | 13 | 0.225 | 0.2407 |

**McNemar (deminh_vs_self_check): n_discordant=27** — first run past the ~25
threshold, so this is the first *interpretable* comparison. deminh_right_self_wrong=18,
self_right_deminh_wrong=9, chi2=2.3704, **p=0.1237** — trending toward deminh
(2:1 in discordant pairs) but not significant at 0.05. Needs a bigger n to
resolve, not a bigger effect.

**detection_by_category** (n per category: arithmetic_slip=13, invented_figure=15,
scale_error=15, sign_error=15, wrong_extraction=14, **wrong_operation=0**):
- self_check recall: arithmetic_slip 0.85, scale_error 0.93, invented_figure/sign_error/wrong_extraction 1.0
- deminh recall: **1.0 on every present category** — matches `EXPECTED_CATCHER`
  predictions (recompute → arithmetic_slip/scale/sign, provenance → invented_figure/wrong_extraction)

**Flags:** self_check fires via `self_check` mechanism only (69). deminh fires via
`provenance` (97) and `recompute` (72) — both mechanisms active, consistent with I4/I5.

**Findings to carry into the dissertation:**
1. **Both verifiers over-flag heavily** (FPR 0.83–0.89). Neither is close to a
   usable false-positive rate on its own. deminh is *less* over-triggering than
   self_check but not by a wide margin — this tempers the headline story and
   should be reported alongside the accuracy gain, not hidden under it.
2. **deminh repairs ~2.7x more often than self_check** (27 vs 10) but also
   **harms ~4.3x more often proportionally** (harm_rate 0.24 vs 0.056). Net
   accuracy delta still favours deminh (+8.05pp vs +4.02pp) because repair
   volume dominates, but the harm-rate gap is a real cost worth its own line
   in the results chapter, not just the net delta.
3. **wrong_operation category got zero surviving corrupted samples** at this n
   — round-robin category assignment collided with the 20 generation-skips.
   Category balance isn't guaranteed once skips are subtracted; re-check at
   larger n or seed the skip-robust assignment differently.
4. Base model accuracy at this n (31.0%) is meaningfully higher than the
   n=44 pilot's 11.4% — the pilot's base-rate number was not representative;
   don't quote pilot accuracy figures in the writeup, only run_001 and later.

---

## FR5 — identity coverage measurement

- Date: 2026-08-07/08 (overnight run)
- `scripts/measure_coverage.py`, backend ollama `qwen3.5:4b`, 50 fresh FinQA
  records (offset=700), Extractor only, no injection, no arms.
- **Result: `coverage_any = 0.0`.** Zero of 50 records admit any of the three
  `DEFAULT_IDENTITIES` (balance_sheet, gross_profit, operating_income).
  `n_extract_failed = 0` — this is a real measurement, not an extraction
  failure artefact.
- Checked `_canonical`/`applicable`/`SYNONYMS` in identities.py by hand — no
  bug found. The mechanism requires the Extractor to have pulled *all*
  components of an identity (e.g. assets, liabilities, and equity together)
  for a single question. FinQA questions are narrowly scoped to whatever
  answers that one question, so the Extractor typically returns 1-3 figures,
  not a full statement section. Structurally, most single-question contexts
  cannot co-produce the inputs an identity needs.
- **This is FR5's answer: on real FinQA under this pipeline's per-question
  extraction scope, the identity mechanism's applicable population is ~0%
  with the current 3 identities.** State this plainly in the dissertation —
  per CLAUDE.md, low coverage bounds what the mechanism can contribute, it
  doesn't invalidate the other two. It does mean deminh's detection wins this
  run are coming entirely from `provenance` + `recompute`, not `identities`
  — matches `flags_by_mechanism` below (identities never appears).
- Open question for the write-up: does this call for more identities, or is
  it evidence that per-question extraction scope is the wrong level for
  cross-derivation checks (would need whole-statement extraction instead)?
  Worth raising with the supervisor rather than deciding unilaterally.

---

## run_002

- Date: 2026-08-08 (overnight, scheduled 20:31, executed autonomously)
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0, top_p 1.0
- Dataset: finqa, `FinQA/dataset/test.json`, **offset=200**, limit 350
  (records 200-549 — deliberately disjoint from run_001's 0-199, since
  decoding is pinned and re-processing the same slice would reproduce
  identical output)
- Prompts/taxonomy: unchanged since run_001 (I2, I7)
- Mid-run incident: Ollama had stopped at some point after the daytime
  session ended. First restart attempt (`ollama serve` from git-bash) came
  up against an empty model directory (wrong env/launch path on Windows —
  bare CLI serve vs the packaged `ollama app.exe` resolve the models
  directory differently) and every call 404'd for ~50 wasted FR5 calls
  before this was caught and fixed by killing that process and launching
  `ollama app.exe` properly. Noted here per I2/I7 spirit — say so rather
  than let it pass silently. Cost was small (the 50 fast-failing calls, not
  the 15-minute FR5 budget) because the failure was immediate (404s), not
  hanging.
- Status: **complete**. 350 loaded, 41 skipped (generation produced no
  claim) → parse-failure rate **11.7%**, consistent with run_001's 10%.
  309 records/arm, 123 corrupted, 4 excluded from mitigation for no gold.

| Arm | precision | recall | FPR | acc_before | acc_after | delta | repaired | harmed | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.318 | 0.318 | 0.0 | - | - | - | - |
| self_check | 0.419 | 0.9675 | 0.8871 | 0.318 | 0.3475 | +0.0295 | 17 | 8 | 0.0817 | 0.0825 |
| deminh | 0.4485 | 0.9919 | 0.8065 | 0.318 | 0.3344 | **+0.0164** | 25 | 20 | 0.1202 | 0.2062 |

**McNemar (deminh_vs_self_check), run_002 alone: n_discordant=42 — chi2=6.881,
p=0.0087. Significant at 0.05.** deminh_right_self_wrong=30,
self_right_deminh_wrong=12 (2.5:1).

**Category applicability — now measured, not guessed** (per-category `n` in
detection_by_category, plus new `"Category X did not apply"` logging added
today): of 84 logged applicability failures, **69 are wrong_operation**
(only 2 of ~71 attempts actually applied — a 97% failure rate) and 15 are
wrong_extraction. wrong_operation requires the Analyst's expression to
contain a literal `+ - * /`; most FinQA claims are direct single-figure
lookups with no operator to corrupt. This confirms and quantifies the gap
run_001 first showed as `wrong_operation n=0` — it is a structural property
of the dataset/model combination, not an unlucky round-robin collision.
wrong_extraction's ~44% failure rate is milder (needs 2 figures with
different values in the same extraction).

**detection_by_category:** deminh recall 1.0 on all categories except
scale_error (0.9615); self_check recall ranges 0.885 (arithmetic_slip) to
1.0 (scale/sign/wrong_extraction/wrong_operation, on n=2 for the last).
Still matches `EXPECTED_CATCHER` direction — deminh's mechanisms are
structurally suited to the categories they're assigned to.

**Flags:** self_check via `self_check` only (119). deminh via `provenance`
(207) and `recompute` (119) — `identities` never fires, consistent with the
FR5 0% coverage result above.

**The one finding that needs its own paragraph in the dissertation:**
deminh wins detection decisively (better precision/recall/FPR, and now a
*significant* McNemar at n=42 discordant) but its **net mitigation accuracy
gain is smaller than self_check's in this run** (+1.64pp vs +2.95pp) —
the reverse of run_001, where deminh's net gain was bigger (+8.05pp vs
+4.02pp). The reason is harm_rate: deminh repairs more (repair_rate 0.120
vs 0.082) but harms more than twice as often proportionally (0.206 vs
0.083), and in run_002 that harm ate more of the gain than the extra
repairs bought back. **Detecting more accurately does not automatically
mean correcting more accurately** — recompute's repairs are only as good as
whether "recompute the stated expression" actually recovers the intended
value, and per the wrong_operation finding above, a faithfully-executed
wrong operation is invisible to recompute by design (injection.py's own
comment says so). This is exactly the kind of result CLAUDE.md says to
report honestly rather than tune away.

---

## Pooled run_001 + run_002 (disjoint FinQA slices, n=489 total)

Valid for McNemar/precision/recall pooling since both runs share pinned
decoding, identical prompts/taxonomy, and cover non-overlapping items.
Computed by hand from the two runs' raw tp/fp/fn/tn and b/c counts (not
re-run through code — worth adding a small script if this becomes a
recurring step rather than a one-off).

| Arm | precision | recall | FPR | acc_before | acc_after | delta | repaired | harmed |
|---|---|---|---|---|---|---|---|---|
| self_check | 0.4187 | 0.9641 | 0.8878 | 0.3152 | 0.3486 | +0.0334 | 27 | 11 |
| deminh | 0.4470 | 0.9949 | 0.8163 | 0.3152 | 0.3549 | +0.0397 | 52 | 33 |

**Pooled McNemar: b (deminh_right_self_wrong)=48, c (self_right_deminh_wrong)=21,
n_discordant=69, chi2=9.797, p=0.00175.** Well past the ~25 threshold and
clearly significant — this is the strongest, largest-n statement the data
currently supports: **deminh detects corruption more accurately than
self_check, at a level unlikely to be chance (p<0.002, n=489).** Report this
pooled number as the headline, with the per-run mitigation-accuracy caveat
above stated alongside it, not omitted.

**Still open before writing this up as final:** harm_rate is trending
upward with n (deminh: 0.20 → 0.21 pooled; a similar pattern in self_check:
0.056 → 0.083) rather than settling — worth another batch before treating
either harm_rate as stable enough to quote a single number for.

---

## run_003a / run_003b — scheduled 2026-08-15 00:00, unattended

- Scheduled, not yet executed at time of writing. Windows Task Scheduler task
  `deminh_run_003` runs `scripts/run_003_overnight.ps1` at 00:00.
- Backend: ollama, `qwen3.5:4b`, seed 42, temp 0.0, top_p 1.0 — identical to
  run_001 and run_002, so all three pool.
- Dataset: finqa, `FinQA/dataset/test.json` (1147 records).
  **run_003a = offset 550, limit 175. run_003b = offset 725, limit 175.**
  Disjoint from run_001 (0–199) and run_002 (200–549).
- Prompts/taxonomy: unchanged since run_001 (I2, I7).
- Injection: CLI defaults. Note for the record — with
  `ExperimentConfig.balanced_categories=True` (the default), corruption is a
  deterministic index round-robin (`experiment.py`: `if index % 2 == 0`), so
  `--seed` and `--injection-rate` do **not** influence which records are
  corrupted or with what. Earlier entries citing an injection seed were citing
  a parameter that has no effect on the balanced path.
- **Split into two chunks deliberately.** `Experiment.save()` is called once,
  after the entire batch completes; nothing is written incrementally. A crash
  at record 174 of 175 loses the whole chunk. Two 175-record chunks writing
  separate result dirs cap that loss at one chunk, and each chunk is
  individually poolable. run_003b is attempted even if run_003a fails.
- Pre-run state, recorded before the fact: the Ollama server was **down** at
  21:32 (backend process had exited; only the tray app was alive). The model
  `qwen3.5:4b` was confirmed present on disk at `G:\LLMs` — note that
  `OLLAMA_MODELS=G:\LLMs` is known only to the packaged app and is *not* a
  user or machine environment variable, which is precisely the trap that cost
  run_002 ~50 wasted calls. The wrapper therefore sets it explicitly, and
  refuses to start the batch unless `qwen3.5:4b` is visible in `/api/tags`.
- Expected wall clock: run_002 took ~6h for 350 records, so ~6h total,
  finishing ~06:00.

---

## Analysis tooling — `scripts/rescore.py` (2026-08-14, no model calls)

Re-scores detection against **answer-correctness** as well as injection status,
over one or more run dirs, with pooling. Offline: reads only the committed
`records_*.json`.

Validated two ways against run_002:

1. Reproduces `summary.json`'s injection-based detection block **exactly** for
   all three arms (asserted in `tests/test_rescore.py`).
2. Reproduces the hand-computed decomposition in
   `ANALYSIS_REPAIR_POLICY_AND_FPR.md` exactly — deminh, non-injected records,
   pre-verification answer: TP=89, FP=60, FN=22, TN=14, 1 excluded for no gold,
   precision 0.5973, recall 0.8018.

Building it surfaced that the analysis document's "precision rises 0.45 → 0.60"
paired an all-records figure with a clean-subpopulation figure. A clarification
is appended to that document; the like-for-like all-records rise is
0.4485 → 0.6716. **The direction of the finding is unchanged and understated.**

The substantive result to carry into the write-up: under correctness ground
truth over all 309 records, deminh's precision advantage over self_check
disappears (0.6716 vs 0.6714) and self_check leads on recall (0.9447 vs 0.8867).
deminh's measured superiority is specifically at detecting *injected* errors.
Report the pooled McNemar as a statement about the injected corpus, not as a
general claim about catching wrong answers.


---

## run_003a / run_003b — executed 2026-08-14 23:43 to 2026-08-15 04:20

Launched early on request rather than waiting for the 00:00 trigger. Config
exactly as registered in the preceding entry. Both chunks completed, exit 0,
**zero connection/HTTP errors** — the preflight model-visibility gate did its
job and the run_002 empty-model-store failure did not recur.

- run_003a: offset 550, limit 175 → 154 min. 175 loaded, 21 skipped
  (parse-failure rate **12.0%**), 157 records/arm.
- run_003b: offset 725, limit 175 → 132 min. 175 loaded, 22 skipped
  (parse-failure rate **12.6%**), 156 records/arm.
- Parse-failure rate is stable across all four runs: 10.0%, 11.7%, 12.0%, 12.6%.

| Run | Arm | precision | recall | FPR | accB | accA | delta | repaired | harmed |
|---|---|---|---|---|---|---|---|---|---|
| 003a | self_check | 0.4255 | 0.9091 | 0.8901 | 0.2987 | 0.3117 | +0.0130 | 8 | 6 |
| 003a | deminh | 0.4444 | 0.9846 | 0.8696 | 0.2987 | 0.3117 | +0.0130 | 12 | 10 |
| 003b | self_check | 0.3986 | 0.9500 | 0.8958 | 0.3072 | 0.3072 | +0.0000 | 8 | 8 |
| 003b | deminh | 0.4286 | 1.0000 | 0.8333 | 0.3072 | 0.3464 | +0.0392 | 16 | 10 |

McNemar per chunk: 003a b=16 c=10 n_disc=26 p=0.327; 003b b=16 c=7 n_disc=23
p=0.095. Neither chunk is individually conclusive, as expected at n≈156.

### Pooled across all four runs (n=802, FinQA test.json records 0–899)

| Arm | precision | recall | FPR | accB | accA | delta | repaired | harmed | repair_rate | harm_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| no_verifier | 0.0 | 0.0 | 0.0 | 0.3104 | 0.3104 | 0.0 | - | - | - | - |
| self_check | 0.4161 | 0.9502 | 0.8898 | 0.3104 | 0.3333 | +0.0229 | 43 | 25 | 0.0793 | 0.1025 |
| deminh | 0.4429 | 0.9938 | 0.8299 | 0.3104 | 0.3448 | +0.0344 | 80 | 53 | 0.1476 | 0.2172 |

**Pooled McNemar: b=80, c=38, n_discordant=118, chi2=14.2458, p=0.00016.**
Up from n_discordant=69, p=0.00175 at n=489. This is the headline number.

harm_rate has now settled rather than continuing to climb: deminh 0.2407 →
0.2062 → 0.2172 pooled across runs; self_check 0.0556 → 0.0825 → 0.1025. The
open question in the run_002 entry ("worth another batch before quoting a
single number") is answered for deminh — **~0.21** is stable across 802 items.

Correctness-based re-scoring (`scripts/rescore.py`, all records, final_answer),
pooled n=802, 16 excluded for no gold:

| Arm | precision | recall | F1 | FPR |
|---|---|---|---|---|
| self_check | 0.6847 | 0.9408 | 0.7926 | 0.8664 |
| deminh | 0.6676 | 0.9126 | 0.7711 | 0.8635 |

Confirms the run_002 observation at four times the sample: **under
answer-correctness ground truth self_check is marginally ahead of deminh on both
precision and recall**, the reverse of the injection-based ordering. deminh's
advantage is specifically at detecting *injected* errors.

### Defect found while checking these results — injection is not arm-invariant

**This affects run_001 and run_002 as well, and contradicts I1.**

`InjectionHarness` holds one RNG (`self.rng`) and `Experiment.run` calls
`corrupt_with` once per arm per record, in a fixed arm order. The RNG state
therefore advances between arms, so each arm receives a *different draw* for the
same record and category. Measured across the record dumps:

| Run | corrupted records | records whose injected VALUE differs across arms | category differs | applicability differs |
|---|---|---|---|---|
| run_001 | 72 | 60 (83%) | 0 | 0 |
| run_002 | 123 | 104 (85%) | 0 | 0 |
| run_003a | 66 | 51 (77%) | 0 | 1 |
| run_003b | 60 | 51 (85%) | 0 | 1 |

Example (run_001, `AES/2010/page_227.pdf-4`, scale_error): no_verifier got
690000.0, self_check 690.0, deminh 690000000000.0. A x1e9 scale error is far
easier to catch than a x1e-3 one, so the arms are not facing equally difficult
instances.

What is *not* broken, and why the existing results are still usable:

- The injected **category** is identical across arms in all 802 records, so
  `detection_by_category` is sound.
- **Whether** a record was corrupted is identical in 800 of 802 records; the two
  exceptions are `wrong_extraction` non-applications (run_003a
  `AES/2002/page_128.pdf-4`, run_003b `DVN/2015/page_79.pdf-2`). This is why
  `n_corrupted` reads 66/66/65 and 59/60/60 rather than being equal.
- The draws are independent and the arm order is fixed, so this injects
  **noise into the paired comparison, not bias toward an arm**. It inflates the
  variance of McNemar rather than shifting b vs c systematically.

Honest statement of the consequence: the paired design is weaker than I1
intends — arms see the same error *type* on the same record but not the same
error *instance*. The pooled p=0.00016 is very unlikely to be an artefact of
this, given the direction is consistent across all four independent slices
(b>c in every one), but the limitation must be stated rather than discovered by
a marker.

**Not fixed, and deliberately not fixed unilaterally** — this is an I1/I7-class
change. The fix is to reseed the harness RNG per (record, category) before each
arm's `corrupt_with`, making the injected instance identical across arms. That
invalidates all four runs and costs a full ~12h re-run of 802 records. The
alternative is to report the limitation as above. Supervisor decision.

