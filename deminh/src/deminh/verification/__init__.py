"""Verification mechanisms.

Three deterministic mechanisms (recompute, provenance, identities) and one
model-based baseline (selfcheck). The distinction matters: the deterministic
mechanisms are independent *by construction* because they depend on no model's
judgement. Do not describe them as "a second model verifying" — that is VeNRA's
design, not this one.
"""
