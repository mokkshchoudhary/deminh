"""Mechanism 1: deterministic recomputation.

Takes the Analyst's expression, binds the variables to extracted figures, and
re-evaluates it in Python. No model is consulted. If the recomputed value
differs from the claimed value, the claim is flagged AND repaired — recomputation
is the one mechanism that can supply a corrected number rather than merely
objecting.

Catches: arithmetic slips.
Does NOT catch: wrong extraction, invented figures, wrong choice of operation.
The arithmetic can be flawless on the wrong inputs. Say this explicitly in the
dissertation; it is the reason a single mechanism is not sufficient and the
reason your per-category breakdown is interesting.

`eval()` is not used. An untrusted expression from a language model is exactly
the input `eval` should never see.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Optional

from ..numeric import close_enough
from ..schemas import (
    Flag,
    Mechanism,
    NumericClaim,
    PipelineRecord,
    Severity,
)

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_FUNCS = {
    "sum": lambda *a: sum(a[0]) if len(a) == 1 and isinstance(a[0], (list, tuple)) else sum(a),
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
}


class ExpressionError(ValueError):
    """Raised when an expression is malformed or uses disallowed constructs."""


def safe_eval(expression: str, variables: dict[str, float]) -> float:
    """Evaluate a restricted arithmetic expression."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Cannot parse expression {expression!r}: {exc}") from exc
    return float(_eval_node(tree.body, variables))


def _eval_node(node: ast.AST, variables: dict[str, float]):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ExpressionError(f"Disallowed constant: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpressionError(f"Unbound variable: {node.id}")
        return variables[node.id]

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError(f"Disallowed operator: {type(node.op).__name__}")
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if op is operator.truediv and right == 0:
            raise ExpressionError("Division by zero")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError(f"Disallowed unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand, variables))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ExpressionError("Disallowed function call")
        args = [_eval_node(a, variables) for a in node.args]
        return _FUNCS[node.func.id](*args)

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(e, variables) for e in node.elts]

    raise ExpressionError(f"Disallowed syntax: {type(node).__name__}")


def check_claim(claim: NumericClaim, record: PipelineRecord,
                rel_tol: float = 1e-3) -> tuple[bool, Optional[Flag]]:
    """Return (was_checkable, flag_or_None)."""
    derivation = claim.derivation
    if derivation is None:
        return False, None

    variables: dict[str, float] = {}
    for var, fig_id in derivation.bindings.items():
        figure = record.figure_by_id(fig_id)
        if figure is None:
            return True, Flag(
                claim_id=claim.id,
                mechanism=Mechanism.RECOMPUTE,
                message=f"Expression references unknown figure id {fig_id!r} for variable {var!r}.",
                severity=Severity.ERROR,
            )
        variables[var] = figure.value
        # Small models sometimes write the figure id itself into the expression
        # instead of the semantic variable name they just declared in bindings.
        # Alias both so recomputation still runs against a figure that is,
        # either way, one the model actually named.
        variables[fig_id] = figure.value

    try:
        recomputed = safe_eval(derivation.expression, variables)
    except ExpressionError as exc:
        return True, Flag(
            claim_id=claim.id,
            mechanism=Mechanism.RECOMPUTE,
            message=f"Expression could not be evaluated: {exc}",
            severity=Severity.ERROR,
        )

    if close_enough(recomputed, claim.value, rel_tol=rel_tol):
        return True, None

    return True, Flag(
        claim_id=claim.id,
        mechanism=Mechanism.RECOMPUTE,
        message=(
            f"Claimed {claim.value} but {derivation.expression} evaluates to "
            f"{recomputed} under the extracted figures."
        ),
        severity=Severity.ERROR,
        proposed_value=recomputed,
    )
