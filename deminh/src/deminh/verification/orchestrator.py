"""Runs the verification mechanisms and decides what to do about the flags.

The repair policy is a design decision with direct consequences for your harm
rate. Repairing aggressively raises the chance of turning a correct answer into a
wrong one; repairing conservatively lowers your mitigation gain. The policy is
made explicit and configurable here so you can report which one you used, and
ideally show results under more than one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..llm import LLMBackend
from ..schemas import (
    Flag,
    Mechanism,
    PipelineRecord,
    Severity,
    VerificationReport,
)
from . import identities as identity_mod
from . import provenance as provenance_mod
from . import recompute as recompute_mod
from .selfcheck import SelfChecker


class RepairPolicy(str, Enum):
    NONE = "none"                 # flag only, never substitute
    RECOMPUTE_ONLY = "recompute"  # trust only deterministic recomputation
    ANY_PROPOSAL = "any"          # accept any mechanism's proposed value


@dataclass
class VerifierConfig:
    use_recompute: bool = True
    use_provenance: bool = True
    use_identities: bool = True
    use_self_check: bool = False
    repair_policy: RepairPolicy = RepairPolicy.RECOMPUTE_ONLY
    rel_tol: float = 1e-3


class Verifier:
    def __init__(self, config: VerifierConfig,
                 backend: Optional[LLMBackend] = None,
                 identity_set: Optional[list[identity_mod.Identity]] = None):
        self.config = config
        self.identity_set = identity_set or identity_mod.DEFAULT_IDENTITIES
        self.self_checker = SelfChecker(backend) if config.use_self_check else None
        if config.use_self_check and backend is None:
            raise ValueError("Self-check requires a model backend.")

    def run(self, record: PipelineRecord) -> VerificationReport:
        report = VerificationReport()

        identity_applied = False
        identity_flags: list[Flag] = []
        if self.config.use_identities:
            identity_applied, identity_flags = identity_mod.check_record(
                record, self.identity_set
            )
        report.flags.extend(identity_flags)

        for claim in record.claims:
            covered = identity_applied and any(
                f.claim_id == claim.id for f in identity_flags
            )

            if self.config.use_recompute:
                checkable, flag = recompute_mod.check_claim(
                    claim, record, rel_tol=self.config.rel_tol
                )
                covered = covered or checkable
                if flag:
                    report.flags.append(flag)

            if self.config.use_provenance:
                checkable, flags = provenance_mod.check_claim(claim, record)
                covered = covered or checkable
                report.flags.extend(flags)

            if self.self_checker is not None:
                checkable, flag = self.self_checker.check_claim(claim, record)
                covered = covered or checkable
                if flag:
                    report.flags.append(flag)

            # Identity coverage counts even when the identity was satisfied.
            if self.config.use_identities and identity_applied:
                covered = True

            (report.claims_checked if covered else report.claims_uncovered).append(claim.id)

        self._apply_repairs(record, report)
        return report

    def _apply_repairs(self, record: PipelineRecord, report: VerificationReport) -> None:
        policy = self.config.repair_policy
        if policy is RepairPolicy.NONE:
            return

        allowed = (
            {Mechanism.RECOMPUTE}
            if policy is RepairPolicy.RECOMPUTE_ONLY
            else set(Mechanism)
        )

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
