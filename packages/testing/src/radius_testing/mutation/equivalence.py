"""Equivalent-mutant heuristics (EV-10).

A surviving mutant is evidence about a test only if it is *not* semantically
equivalent to the original. Equivalence is undecidable, so this module only marks
mutants as ``equivalent_suspect`` using cheap, explainable checks. A suspect:

* is excluded from the ``d_mut`` denominator **by policy** (``exclude_suspects``),
* is always reported (never silently dropped),
* is never used to claim a verdict: survivors alone never prove a criterion
  broken, and suspects never prove it healthy.

Checks (in order): identical AST, identical bytecode, then syntactic patterns:
neutral literal operand (``x + 0``, ``x * 1``), identical operands (``a and a``,
swapped identical arguments), removal of side-effect-free logging calls,
exception-message string constants.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from types import CodeType

from radius_testing.mutation.operators import Mutant

LOGGING_NAMES = frozenset({"print", "logging", "logger", "log", "LOGGER", "LOG"})


@dataclass(frozen=True, slots=True)
class EquivalenceVerdict:
    suspect: bool
    method: str | None = None  # "ast" | "bytecode" | "pattern"
    reason: str | None = None


NOT_SUSPECT = EquivalenceVerdict(False)


def _code_equal(a: CodeType, b: CodeType) -> bool:
    if a.co_code != b.co_code or a.co_names != b.co_names or a.co_varnames != b.co_varnames:
        return False
    if len(a.co_consts) != len(b.co_consts):
        return False
    for x, y in zip(a.co_consts, b.co_consts, strict=True):
        if isinstance(x, CodeType) and isinstance(y, CodeType):
            if not _code_equal(x, y):
                return False
        elif type(x) is not type(y) or x != y:
            return False
    return True


def _find_node(tree: ast.AST, mutant: Mutant) -> tuple[ast.AST | None, dict[int, ast.AST]]:
    parents: dict[int, ast.AST] = {}
    found: ast.AST | None = None
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
            if (
                found is None
                and getattr(child, "lineno", None) == mutant.lineno
                and getattr(child, "col_offset", None) == mutant.col
                and getattr(child, "end_lineno", None) == mutant.end_lineno
                and getattr(child, "end_col_offset", None) == mutant.end_col
                and _matches_operator(child, mutant.operator)
            ):
                found = child
    return found, parents


def _matches_operator(node: ast.AST, operator: str) -> bool:
    kinds: dict[str, tuple[type, ...]] = {
        "ROR": (ast.Compare,),
        "AOR": (ast.BinOp, ast.AugAssign),
        "BOOL": (ast.BoolOp,),
        "CRM": (ast.BoolOp, ast.If, ast.While),
        "NEG": (ast.UnaryOp, ast.If, ast.While, ast.IfExp),
        "CON": (ast.Constant,),
        "RET": (ast.Return,),
        "EXC": (ast.Raise,),
        "CALL": (ast.Expr,),
        "ARG": (ast.Call,),
    }
    return isinstance(node, kinds.get(operator, ()))


def _dump(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=False)


def _is_const(node: ast.AST, value: object) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value == value


def _call_root_name(call: ast.Call) -> str:
    func = call.func
    while isinstance(func, ast.Attribute):
        func = func.value
    return func.id if isinstance(func, ast.Name) else ""


def _pattern(node: ast.AST, parents: dict[int, ast.AST], mutant: Mutant) -> str | None:
    op = mutant.operator
    if op == "AOR" and isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)) and _is_const(node.right, 0):
            return "neutral operand: x +/- 0"
        if isinstance(node.op, (ast.Mult, ast.Div)) and _is_const(node.right, 1):
            return "neutral operand: x * / 1"
        if isinstance(node.op, ast.Mult) and _is_const(node.left, 1):
            return "neutral operand: 1 * x"
    if op in {"BOOL", "CRM"} and isinstance(node, ast.BoolOp):
        dumps = [_dump(v) for v in node.values]
        if len(set(dumps)) < len(dumps):
            return "identical operands: a and a / a or a"
    if op == "ARG" and isinstance(node, ast.Call) and len(node.args) >= 2:
        if _dump(node.args[0]) == _dump(node.args[1]):
            return "identical arguments swapped"
    if op == "CALL" and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _call_root_name(node.value) in LOGGING_NAMES:
            return "removed logging/print call (no behavioural effect)"
    if op == "CON" and isinstance(node, ast.Constant) and isinstance(node.value, str):
        parent = parents.get(id(node))
        grand = parents.get(id(parent)) if parent is not None else None
        if isinstance(parent, ast.Call) and isinstance(grand, ast.Raise):
            return "exception message constant"
    return None


def detect_equivalent(original_source: str, mutant: Mutant) -> EquivalenceVerdict:
    """Return whether ``mutant`` is a likely equivalent mutant of ``original_source``."""

    try:
        orig_tree = ast.parse(original_source)
        mut_tree = ast.parse(mutant.mutated_source)
    except SyntaxError:
        return NOT_SUSPECT
    if _dump(orig_tree) == _dump(mut_tree):
        return EquivalenceVerdict(True, "ast", "identical AST after normalisation")
    try:
        if _code_equal(
            compile(orig_tree, "<orig>", "exec"), compile(mut_tree, "<mut>", "exec")
        ):
            return EquivalenceVerdict(True, "bytecode", "identical bytecode")
    except (SyntaxError, ValueError, RecursionError):
        return NOT_SUSPECT
    node, parents = _find_node(orig_tree, mutant)
    if node is not None:
        reason = _pattern(node, parents, mutant)
        if reason:
            return EquivalenceVerdict(True, "pattern", reason)
    return NOT_SUSPECT
