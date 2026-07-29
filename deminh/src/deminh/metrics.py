"""Evaluation metrics.

Two regimes, kept strictly separate, as in your notes:

  DETECTION  - did the verifier notice the number was wrong?
               precision, recall, F1, and false-positive rate, broken down by
               injected error category.

  MITIGATION - did the end-to-end answer get better?
               accuracy before and after verification, repair rate, and HARM
               RATE: the proportion of previously-correct answers that the
               verifier broke.

Report the false-positive rate and the harm rate as prominently as recall. A
verifier that flags everything achieves perfect recall and is useless; if you
present recall alone, an examiner will ask about exactly this and you want the
answer already in the table.

Because all three configurations run on the same items, the comparison is
*paired*. Use McNemar's test, not a two-sample proportion test — the latter
throws away the pairing and is the wrong test for this design.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .numeric import close_enough
from .schemas import PipelineRecord


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Of the answers that were actually correct, how many were flagged?"""
        denom = self.fp + self.tn
        return self.fp / denom if denom else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
        }


def was_corrupted(record: PipelineRecord) -> bool:
    return bool(record.injected)


def was_flagged(record: PipelineRecord) -> bool:
    return bool(record.report and record.report.flagged_claim_ids)


def detection_metrics(records: list[PipelineRecord]) -> ConfusionMatrix:
    matrix = ConfusionMatrix()
    for record in records:
        actual, predicted = was_corrupted(record), was_flagged(record)
        if actual and predicted:
            matrix.tp += 1
        elif actual and not predicted:
            matrix.fn += 1
        elif not actual and predicted:
            matrix.fp += 1
        else:
            matrix.tn += 1
    return matrix


def detection_by_category(records: list[PipelineRecord]) -> dict[str, dict[str, float]]:
    """Recall per injected error category.

    This table is the substance of the contribution. A single aggregate recall
    number tells you independence helped; the breakdown tells you *which kinds*
    of numerical error independent checking reaches and which slip through.
    """
    buckets: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        if not record.injected:
            continue
        detected = was_flagged(record)
        for injection in record.injected:
            buckets[injection.category].append(detected)

    return {
        category: {
            "n": len(results),
            "recall": round(sum(results) / len(results), 4) if results else 0.0,
        }
        for category, results in sorted(buckets.items())
    }


def detection_by_mechanism(records: list[PipelineRecord]) -> dict[str, int]:
    """Which mechanism raised the flag? Shows whether all three earn their place."""
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        if not (record.report and record.injected):
            continue
        for flag in record.report.flags:
            counts[flag.mechanism.value] += 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# Mitigation
# --------------------------------------------------------------------------

@dataclass
class MitigationMetrics:
    n: int = 0
    correct_before: int = 0
    correct_after: int = 0
    repaired: int = 0        # was wrong -> became right
    harmed: int = 0          # was right -> became wrong
    unchanged: int = 0
    no_gold: int = 0

    @property
    def accuracy_before(self) -> float:
        return self.correct_before / self.n if self.n else 0.0

    @property
    def accuracy_after(self) -> float:
        return self.correct_after / self.n if self.n else 0.0

    @property
    def repair_rate(self) -> float:
        wrong_before = self.n - self.correct_before
        return self.repaired / wrong_before if wrong_before else 0.0

    @property
    def harm_rate(self) -> float:
        return self.harmed / self.correct_before if self.correct_before else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "n": self.n,
            "accuracy_before": round(self.accuracy_before, 4),
            "accuracy_after": round(self.accuracy_after, 4),
            "delta": round(self.accuracy_after - self.accuracy_before, 4),
            "repaired": self.repaired,
            "harmed": self.harmed,
            "repair_rate": round(self.repair_rate, 4),
            "harm_rate": round(self.harm_rate, 4),
            "skipped_no_gold": self.no_gold,
        }


def _percent_aware_match(value: Optional[float], gold: float, question: str,
                         rel_tol: float) -> bool:
    """Match `value` against `gold`, allowing a x100 flip for percentage questions.

    FinQA's `exe_ans` field is inconsistent about whether a "percentage"
    question's answer is stored as a fraction (0.935) or as a whole percent
    (24.69) - it depends on which arithmetic program produced it, not on the
    question wording. Without this, accuracy is deflated by a formatting
    convention rather than a real reasoning error. This only widens the
    *scoring* comparison; it does not touch the scale_error detection
    mechanisms, which still compare figures at their literal extracted scale.
    """
    if close_enough(value, gold, rel_tol=rel_tol):
        return True
    if "percent" in (question or "").lower():
        if close_enough(value * 100, gold, rel_tol=rel_tol):
            return True
        if close_enough(value / 100, gold, rel_tol=rel_tol):
            return True
    return False


def mitigation_metrics(records: list[PipelineRecord],
                       rel_tol: float = 1e-2) -> MitigationMetrics:
    """Compare the pre-verification value against the post-verification value.

    `record.meta["pre_verification_answer"]` must be populated by the runner
    before verification mutates the claim.
    """
    metrics = MitigationMetrics()
    for record in records:
        if record.gold_answer is None:
            metrics.no_gold += 1
            continue

        before = record.meta.get("pre_verification_answer")
        after = record.final_answer
        if before is None:
            before = after

        metrics.n += 1
        ok_before = _percent_aware_match(before, record.gold_answer, record.question, rel_tol)
        ok_after = _percent_aware_match(after, record.gold_answer, record.question, rel_tol)

        metrics.correct_before += int(ok_before)
        metrics.correct_after += int(ok_after)
        if not ok_before and ok_after:
            metrics.repaired += 1
        elif ok_before and not ok_after:
            metrics.harmed += 1
        else:
            metrics.unchanged += 1
    return metrics


# --------------------------------------------------------------------------
# Paired significance testing
# --------------------------------------------------------------------------

@dataclass
class McNemarResult:
    b: int          # A right, B wrong
    c: int          # A wrong, B right
    statistic: float
    p_value: float
    n_discordant: int = field(init=False)

    def __post_init__(self) -> None:
        self.n_discordant = self.b + self.c


def mcnemar(outcomes_a: list[bool], outcomes_b: list[bool],
            continuity_correction: bool = True) -> McNemarResult:
    """Paired test for two configurations run on the same items.

    Only the discordant pairs carry information — items where both arms agree
    tell you nothing about which is better. With few discordant pairs the
    chi-square approximation is poor; report `n_discordant` alongside p and treat
    anything under about 25 with suspicion.
    """
    if len(outcomes_a) != len(outcomes_b):
        raise ValueError("Paired test requires equal-length outcome lists.")

    b = sum(1 for x, y in zip(outcomes_a, outcomes_b) if x and not y)
    c = sum(1 for x, y in zip(outcomes_a, outcomes_b) if y and not x)

    if b + c == 0:
        return McNemarResult(b=b, c=c, statistic=0.0, p_value=1.0)

    numerator = abs(b - c) - (1 if continuity_correction else 0)
    statistic = max(numerator, 0) ** 2 / (b + c)
    p_value = math.erfc(math.sqrt(statistic / 2))  # survival function, 1 d.o.f.
    return McNemarResult(b=b, c=c, statistic=statistic, p_value=p_value)


def bootstrap_ci(values: list[float], n_resamples: int = 2000,
                 alpha: float = 0.05, seed: int = 7) -> tuple[float, float]:
    """Percentile bootstrap interval for a mean. Put these on your bar charts."""
    import random

    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower = means[int((alpha / 2) * n_resamples)]
    upper = means[min(int((1 - alpha / 2) * n_resamples), n_resamples - 1)]
    return (lower, upper)
