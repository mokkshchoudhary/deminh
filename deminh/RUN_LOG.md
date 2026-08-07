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
