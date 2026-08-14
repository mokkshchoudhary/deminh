# Analysis — Repair-Policy Replay and the False-Positive Rate

**Date:** 2026-08-14
**Scope:** read-only investigation against `results/run_002/`. No source or result
files were modified.
**Companion to:** `STATUS_AUDIT.md`

Two questions:

1. Can the repair policy be swapped without re-running the model?
2. Is the ~0.81 false-positive rate a real weakness, or a definitional artifact?

---

## Question 1 — Can repair policy be swapped without re-running the model?

### Answer: **YES.** Post-hoc re-analysis is possible, with zero new LLM calls.

### Proof — all three policies replayed offline against `run_002`

```
=== deminh ===
  NONE             acc_after=0.3180  delta=+0.0000  repaired=0   harmed=0   harm_rate=0.0000
  RECOMPUTE_ONLY   acc_after=0.3344  delta=+0.0164  repaired=25  harmed=20  harm_rate=0.2062
  ANY_PROPOSAL     acc_after=0.3344  delta=+0.0164  repaired=25  harmed=20  harm_rate=0.2062

=== self_check ===
  NONE             acc_after=0.3180  delta=+0.0000  repaired=0   harmed=0   harm_rate=0.0000
  RECOMPUTE_ONLY   acc_after=0.3180  delta=+0.0000  repaired=0   harmed=0   harm_rate=0.0000
  ANY_PROPOSAL     acc_after=0.3475  delta=+0.0295  repaired=17  harmed=8   harm_rate=0.0825
```

The `RECOMPUTE_ONLY` replay reproduces the saved `final_answer` on **309/309
records**, and the derived mitigation figures match `summary.json` exactly
(deminh: +0.0164, 25 repaired, 20 harmed, harm_rate 0.2062; self_check: +0.0295,
17 repaired, 8 harmed, harm_rate 0.0825). The replay is exact, not approximate.

### Why it works — the deciding code

Repair application is a **pure function of the saved flags**.
`verification/orchestrator.py:104-122`:

```python
allowed = ({Mechanism.RECOMPUTE} if policy is RepairPolicy.RECOMPUTE_ONLY
           else set(Mechanism))

for flag in report.flags:
    if flag.severity is not Severity.ERROR:
        continue
    if flag.mechanism not in allowed or flag.proposed_value is None:
        continue
    # First proposal wins; do not let two mechanisms fight over one claim.
    report.repairs.setdefault(flag.claim_id, flag.proposed_value)

for claim_id, value in report.repairs.items():
    claim = record.claim_by_id(claim_id)
    if claim is not None:
        claim.value = value
```

It needs exactly four inputs — `severity`, `mechanism`, `proposed_value`,
`claim_id` — plus the order of the flag list.

What `experiment.py:186-196` writes to `records_*.json`:

```python
rows = [{
    "question_id": r.question_id,
    "question": r.question,
    "gold_answer": r.gold_answer,
    "pre_verification_answer": r.meta.get("pre_verification_answer"),
    "final_answer": r.final_answer,
    "injected": [asdict(i) for i in r.injected],
    "flags": [
        {"claim_id": f.claim_id, "mechanism": f.mechanism.value,
         "message": f.message, "proposed_value": f.proposed_value}
        for f in (r.report.flags if r.report else [])
    ],
    "coverage": r.report.coverage() if r.report else None,
} for r in records]
```

`claim_id`, `mechanism`, `proposed_value` and list order are all present, along
with `pre_verification_answer` — the un-repaired claim value that any replay
must start from.

Two fields are *not* saved. Both turn out to be harmless:

1. **`severity` is absent — but every flag is `Severity.ERROR`.** Grepping all
   four mechanisms: `identities.py:150`, `provenance.py:85`, `provenance.py:94`,
   `recompute.py:126`, `recompute.py:142`, `recompute.py:155`,
   `selfcheck.py:99`. No `WARN` and no `INFO` is ever emitted anywhere in the
   codebase, so the `severity is not Severity.ERROR` guard never filters
   anything, and the field is reconstructible by assumption.

2. **Claim ordering is not saved — but there is exactly one claim per record.**
   `graph.py:93` does `record.claims = [claim_from_derivation(...)]`. Confirmed
   empirically: 0 of 309 records have more than one distinct `claim_id` across
   their flags. So "which claim is `claims[0]`" is never ambiguous.

A third property matters: **there is no cascade.** `_apply_repairs` runs once,
after every mechanism has finished. A repair never triggers re-verification, so
there is no hidden intermediate state that a replay would have to reproduce.

### Every RepairPolicy option

| Value | Behaviour |
|---|---|
| `RepairPolicy.NONE` (`"none"`) | Flag only, never substitute |
| `RepairPolicy.RECOMPUTE_ONLY` (`"recompute"`) | Trust only deterministic recomputation. Default for the deminh arm |
| `RepairPolicy.ANY_PROPOSAL` (`"any"`) | Accept any mechanism's proposed value. Used by the self_check arm |

### Important consequence: the two policies are identical on the deminh arm

`ANY_PROPOSAL` and `RECOMPUTE_ONLY` produce the same result for arm 3. Not
coincidence — structural:

```
flags by mechanism:        {'recompute': 217, 'provenance': 451}
flags WITH proposed_value: {'recompute': 147}
```

Provenance proposes nothing. `provenance.py:85` and `provenance.py:94` construct
`Flag(...)` without a `proposed_value`, exactly as the module docstring states
("This mechanism cannot repair"). Identities never fire at all — FR5 coverage is
0%. So the only repair-capable mechanism in the deminh arm *is* recompute, and
widening the policy admits nothing new.

For CLAUDE.md §6 item 3 ("consider reporting under two policies"): the available
contrast on arm 3 is `NONE` vs `RECOMPUTE_ONLY` — a real one, +0.0000 at
harm_rate 0.0 versus +0.0164 at harm_rate 0.206. But the conservative/aggressive
axis is **not explorable** on arm 3 without adding a second repair-capable
mechanism. State that explicitly rather than let a reader assume the comparison
was declined.

### Limit of offline replay

You can only replay policies over mechanisms that actually ran. Self-check
proposals cannot be retro-fitted onto deminh records, because the self-checker
never executed in that arm. That is an arm-configuration change and does require
a re-run.

---

## Question 2 — Is the false-positive rate real or a definitional artifact?

### Answer: **Mostly artifact.** Three stacked layers, all fixable.

### How positives are counted: per-record, boolean OR

`metrics.py:77-96`:

```python
def was_corrupted(record: PipelineRecord) -> bool:
    return bool(record.injected)

def was_flagged(record: PipelineRecord) -> bool:
    return bool(record.report and record.report.flagged_claim_ids)

def detection_metrics(records):
    matrix = ConfusionMatrix()
    for record in records:
        actual, predicted = was_corrupted(record), was_flagged(record)
        if actual and predicted:       matrix.tp += 1
        elif actual and not predicted: matrix.fn += 1
        elif not actual and predicted: matrix.fp += 1
        else:                          matrix.tn += 1
    return matrix
```

and `schemas.py:123`:

```python
@property
def flagged_claim_ids(self) -> set[str]:
    return {f.claim_id for f in self.flags if f.severity is Severity.ERROR}
```

Every flag is `ERROR`, so every flag qualifies.

**One record = one row in the confusion matrix.** Not per-claim, not per-figure.
Any single flag, on any single figure, condemns the entire record.

Precision and FPR then follow from `ConfusionMatrix`:

```python
precision            = tp / (tp + fp)
false_positive_rate  = fp / (fp + tn)     # of answers that were actually correct, how many flagged?
```

**A false positive is defined as: nothing was injected, and at least one
mechanism raised at least one flag.** Ground truth is "was an error injected",
*not* "is the answer wrong". That is the root of the problem.

run_002 deminh: 186 clean records → 150 flagged (FP), 36 unflagged (TN),
FPR = 150/186 = 0.8065.

### The base-rate collision

Base accuracy is **0.318**. Roughly 68% of un-injected records therefore carry a
*naturally* wrong answer. Measured directly from `records_deminh.json`:

```
clean (non-injected) records: 186    flagged (=FP): 150    not flagged (=TN): 36

of those 150 "false positives":  answer actually WRONG vs gold = 89
                                 answer actually RIGHT        = 60
                                 no gold answer               =  1
  -> 59.3% of "false positives" were flagging a genuinely wrong answer

of the 36 "true negatives":      answer actually WRONG vs gold = 22
```

**59.3% of the "false" positives are correct detections** of the model's own
natural errors — precisely the natural-error population CLAUDE.md §12 item 7
asks to be hand-labelled. Re-scored against answer-correctness instead of
injection: precision rises 0.45 → **0.60**, recall 0.802. And 22 of the 36 "true
negatives" are in fact misses.

### The 10 cases where a genuinely CORRECT number was flagged

There are 60 such records. Ten shown.

| # | question_id | value / gold | Mechanism(s) | Reason text |
|---|---|---|---|---|
| 1 | `FBHS/2017/page_22.pdf-1` | 4.9 / 4.90575 | recompute + provenance x2 | `Claimed 4.9 but (fig_30a524c1 / fig_8e206ab6) evaluates to 4.905746669317955 under the extracted figures.` / `Figure 'cabinets sales' appears to be off by a factor of 1e+06 relative to its source span.` |
| 2 | `CDNS/2018/page_66.pdf-1` | 80.9 / 0.80991 | recompute | `Claimed 80.9 but (fig_acc027d4 - fig_234bb438) / abs(fig_234bb438) * 100 evaluates to 80.99111802347915` |
| 3 | `CDW/2017/page_38.pdf-1` | 16.1 / 0.16127 | recompute + provenance x2 | `Claimed 16.1 but (fig_fb8b8425 / fig_bbce79ea) * 100 evaluates to 16.126781423822532` / `Figure 'gross profit' appears to be off by a factor of 1e+06` |
| 4 | `MSI/2012/page_87.pdf-4` | -18.5 / -0.18519 | recompute + provenance x2 | `Expression references unknown figure id '2200000.0' for variable 'fig_0e4976f7'.` / `Claim depends on missing figure '2700000.0'.` |
| 5 | `IP/2006/page_31.pdf-1` | 19.39 / 0.19391 | provenance x2 | `Figure 'containerboard sales' has value 955.0 which does not appear in its cited span 'u.s . containerboard net sales for 2006 were $ 955 million'` |
| 6 | `IP/2006/page_35.pdf-2` | 12.7 / 0.12702 | provenance x2 | `Figure 'capital spending consumer packaging' cites a span that does not appear verbatim in the document: '\| consumer packaging \| 116 \| 126 \| 198'` |
| 7 | `PKG/2005/page_74.pdf-2` | 37.0 / 36.9 | recompute + provenance x2 | `Claimed 37.0 but (fig_25fbc6b4 + fig_512e1b53) evaluates to 36.900000000000006` / `Figure ... has value 17.6 which does not appear in its cited span '$ 17.6 million'` |
| 8 | `ETR/2016/page_23.pdf-1` | 0.0163 / 0.01639 | recompute + provenance | `Claimed 0.0163 but (fig_62f9bb11 - fig_e15625e8) / abs(fig_e15625e8) evaluates to 0.016390584132519617` |
| 9 | `ZBH/2009/page_58.pdf-4` | 41.5 / 0.41467 | provenance x2 | `Figure 'long-term debt' appears to be off by a factor of 1e+06 relative to its source span.` |
| 10 | `JPM/2014/page_70.pdf-2` | 46.3 / 0.46318 | provenance x2 | `Figure 'net interest income' appears to be off by a factor of 1e+06 relative to its source span.` |

### What the 60 residual false positives decompose into

```
  36  [provenance]  cited table row not a verbatim substring of the rendered doc
  30  [provenance]  model wrote a value where a figure id belongs
  24  [provenance]  figure vs span differ by 1e3 / 1e6 (scale-word expansion)
  23  [recompute]   claim vs expression mismatch  -- 20 of 23 (87%) agree within 1e-2
  14  [recompute]   model wrote a value where a figure id belongs
   8  [provenance]  value not found in its own cited span
```

Four distinct implementation faults. None is a property of deterministic
checking as such:

1. **Tolerance mismatch.** `VerifierConfig.rel_tol = 1e-3`, while gold scoring in
   `mitigation_metrics` uses `rel_tol = 1e-2`. **The verifier is ten times
   stricter than the scorer.** 87% of the recompute false positives are the model
   rounding 4.905746 to 4.9 and being penalised for it. Cases 1, 2, 3, 7, 8.

2. **Scale-word round-trip.** `numeric.py` expands "$955 million" to 955000000,
   after which `provenance.check_figure` compares that value against the literal
   span text, which contains 955. Self-inflicted, and it collides directly with
   the `scale_error` injection category, which relies on the same signal.
   Cases 1, 3, 9, 10.

3. **Verbatim span matching over rendered tables.** `data._render_table` joins
   cells with `" | "`; the model quotes the row back with different spacing or
   embedded newlines; the `span not in haystack` test in `provenance.py:40` then
   fires. Substring equality is the wrong test for a re-rendered table.
   Cases 5, 6, 8.

4. **Binding defect.** The Analyst sometimes writes a literal value where a
   figure id belongs (`'2200000.0'`). `recompute.py:120` and `provenance.py:82`
   then *both* flag the same underlying fault, inflating flag counts. Case 4.
   `recompute.py:133-137` already aliases `fig_id -> value` to work around a
   related failure; this is the case that alias does not reach.

### Verdict

**Artifact, three layers deep — though the mechanisms are not fully exonerated.**

- **Layer 1 — counting.** Per-record boolean OR means one brittle check on one
  figure condemns a record whose answer is correct. Per-claim or per-figure
  scoring would be more honest. Severity tiering would help too (`WARN` for a
  scale suspicion, `ERROR` for an ungrounded value), letting `flagged_claim_ids`
  discriminate. It currently cannot, because nothing in the codebase ever emits a
  non-`ERROR` flag.

- **Layer 2 — ground truth.** "Not injected" does not mean "correct" when base
  accuracy is 0.318. 59.3% of the FPs are real catches, mislabelled by the
  metric's own definition. This is the largest single distortion and it is free
  to fix: re-score offline against `gold_answer`, exactly as in the Question 1
  replay, with no model calls.

- **Layer 3 — the residual 60.** Genuine false alarms, but arising from four
  fixable implementation defects (tolerance, scale round-trip, span matching,
  binding), not from any intrinsic limit on deterministic checking.

**Recommended reporting.** Do not present FPR ≈ 0.81 as evidence that
deterministic verification over-flags. Present it as measured, place the
answer-correctness re-scoring beside it, and then state the four defects. This
also preserves the §5 comparison: self_check's FPR of 0.887 is subject to the
*same* distortion, so the arms remain comparable, and the headline detection
result and the pooled McNemar (p = 0.00175, n = 489) are unaffected — both arms
are scored identically.

---

## Method note

Every number in this document was derived from the committed record dumps in
`results/run_002/` by offline re-analysis. No model was called, and no file in
the repository was modified. The replay logic mirrors
`orchestrator._apply_repairs` and was validated by reproducing the saved
`final_answer` on 309/309 deminh records under `RECOMPUTE_ONLY`.
