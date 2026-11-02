"""AST mutant generator for Python (deterministic, scope-limited).

Operators (id: what it does):

* ``ROR``  relational/boundary: ``< <= > >=`` boundary flips, ``== !=``, ``is``/``is not``, ``in``/``not in``
* ``AOR``  arithmetic: ``+ - * / // % **`` swapped with a neighbour
* ``BOOL`` boolean: ``and`` <-> ``or``
* ``NEG``  negation: ``not x`` -> ``x``; ``if``/``while``/ternary test -> ``not (test)``
* ``CON``  constant: ints/floats +1 (0 -> 1), bool flip, str -> ``"XX" + s`` (``""`` -> ``"XX"``)
* ``RET``  return-value: ``return v`` -> ``return None``
* ``EXC``  raise removal: ``raise ...`` -> ``pass``
* ``CALL`` call removal: expression statement ``f(...)`` -> ``pass``
* ``ARG``  argument swap: first two positional args of a call swapped
* ``CRM``  condition removal: each operand of ``and``/``or`` dropped; ``if``/``while`` test -> ``False``

Identity and order are deterministic: mutants are sorted by
``(path, lineno, col, operator, replacement)`` and the id is a hash of the site and
the textual change, independent of enumeration order. The mutated module text is
produced with :func:`ast.unparse` (formatting of the mutated copy differs from the
original; the original file is never modified).

Scope: only sites whose start line lies in the given line ranges (LK-01
``new_range`` of changed symbols) are mutated. Lines carrying ``# pragma: no mutate``
and docstrings are skipped.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import tokenize
from collections.abc import Callable, Iterable
from dataclasses import dataclass

OPERATOR_IDS: tuple[str, ...] = (
    "ROR",
    "AOR",
    "BOOL",
    "NEG",
    "CON",
    "RET",
    "EXC",
    "CALL",
    "ARG",
    "CRM",
)
PRAGMA = "pragma: no mutate"

# Inclusive 1-based (start, end) line ranges.
Scope = tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class Mutant:
    id: str
    path: str
    operator: str
    lineno: int
    col: int
    end_lineno: int
    end_col: int
    original: str
    replacement: str
    symbol: str
    mutated_source: str
    mutant_hash: str
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "operator": self.operator,
            "line": self.lineno,
            "col": self.col,
            "symbol": self.symbol,
            "original": self.original,
            "replacement": self.replacement,
            "mutant_hash": self.mutant_hash,
        }


# mutate_fn(copied_node) -> replacement node (the same node, edited in place, or a new one)
_Mut = Callable[[ast.AST], ast.AST]
_Cand = tuple[int, str, str, _Mut]

_CMP_SWAPS: dict[type, tuple[type, ...]] = {
    ast.Lt: (ast.LtE,),
    ast.LtE: (ast.Lt,),
    ast.Gt: (ast.GtE,),
    ast.GtE: (ast.Gt,),
    ast.Eq: (ast.NotEq,),
    ast.NotEq: (ast.Eq,),
    ast.Is: (ast.IsNot,),
    ast.IsNot: (ast.Is,),
    ast.In: (ast.NotIn,),
    ast.NotIn: (ast.In,),
}
_ARITH_SWAPS: dict[type, tuple[type, ...]] = {
    ast.Add: (ast.Sub,),
    ast.Sub: (ast.Add,),
    ast.Mult: (ast.Div,),
    ast.Div: (ast.Mult,),
    ast.FloorDiv: (ast.Div,),
    ast.Mod: (ast.Mult,),
    ast.Pow: (ast.Mult,),
}


def _pragma_lines(source: str) -> set[int]:
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and PRAGMA in tok.string:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    return lines


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _fstring_constants(tree: ast.AST) -> set[int]:
    return {
        id(c)
        for n in ast.walk(tree)
        if isinstance(n, ast.JoinedStr)
        for c in ast.walk(n)
        if isinstance(c, ast.Constant)
    }


def _qualnames(tree: ast.Module) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                end = child.end_lineno or child.lineno
                if not isinstance(child, ast.ClassDef):
                    out.append((child.lineno, end, name))
                visit(child, f"{name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _symbol_at(quals: list[tuple[int, int, str]], line: int) -> str:
    best = ""
    best_span = 10**9
    for start, end, name in quals:
        if start <= line <= end and end - start < best_span:
            best, best_span = name, end - start
    return best or "<module>"


def _const(value: object) -> ast.Constant:
    return ast.Constant(value=value)


def _set_cmp(k: int, new: type) -> _Mut:
    def f(n: ast.AST) -> ast.AST:
        n.ops[k] = new()  # type: ignore[attr-defined]
        return n

    return f


def _set_op(new: type) -> _Mut:
    def f(n: ast.AST) -> ast.AST:
        n.op = new()  # type: ignore[attr-defined]
        return n

    return f


def _drop_operand(k: int) -> _Mut:
    def f(n: ast.AST) -> ast.AST:
        vals = [v for j, v in enumerate(n.values) if j != k]  # type: ignore[attr-defined]
        if len(vals) == 1:
            return vals[0]
        n.values = vals  # type: ignore[attr-defined]
        return n

    return f


def _negate_test(n: ast.AST) -> ast.AST:
    n.test = ast.UnaryOp(op=ast.Not(), operand=n.test)  # type: ignore[attr-defined]
    return n


def _false_test(n: ast.AST) -> ast.AST:
    n.test = _const(False)  # type: ignore[attr-defined]
    return n


def _swap_args(n: ast.AST) -> ast.AST:
    n.args[0], n.args[1] = n.args[1], n.args[0]  # type: ignore[attr-defined]
    return n


def _candidates(tree: ast.Module, skip_const: set[int]) -> list[_Cand]:
    cands: list[_Cand] = []
    for idx, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare):
            for k, op in enumerate(node.ops):
                for new in _CMP_SWAPS.get(type(op), ()):
                    cands.append((idx, "ROR", f"{type(op).__name__}->{new.__name__}", _set_cmp(k, new)))
        elif isinstance(node, (ast.BinOp, ast.AugAssign)):
            for new in _ARITH_SWAPS.get(type(node.op), ()):
                cands.append((idx, "AOR", f"{type(node.op).__name__}->{new.__name__}", _set_op(new)))
        elif isinstance(node, ast.BoolOp):
            other = ast.Or if isinstance(node.op, ast.And) else ast.And
            cands.append((idx, "BOOL", f"{type(node.op).__name__}->{other.__name__}", _set_op(other)))
            for k in range(len(node.values)):
                cands.append((idx, "CRM", f"drop operand {k}", _drop_operand(k)))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            cands.append((idx, "NEG", "remove not", lambda n: n.operand))  # type: ignore[attr-defined]
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            cands.append((idx, "NEG", "negate condition", _negate_test))
            if not isinstance(node, ast.IfExp):
                cands.append((idx, "CRM", "condition -> False", _false_test))
        elif isinstance(node, ast.Constant) and id(node) not in skip_const:
            v = node.value
            if isinstance(v, bool):
                cands.append((idx, "CON", f"{v}->{not v}", lambda n: _const(not n.value)))  # type: ignore[attr-defined]
            elif isinstance(v, (int, float)):
                cands.append((idx, "CON", f"{v}->{v + 1}", lambda n: _const(n.value + 1)))  # type: ignore[attr-defined]
            elif isinstance(v, str) and v:
                cands.append((idx, "CON", "str->XX+str", lambda n: _const("XX" + n.value)))  # type: ignore[attr-defined]
            elif isinstance(v, str):
                cands.append((idx, "CON", "empty str->XX", lambda n: _const("XX")))
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                cands.append((idx, "RET", "return->None", lambda n: ast.Return(value=_const(None))))
        elif isinstance(node, ast.Raise):
            cands.append((idx, "EXC", "raise->pass", lambda n: ast.Pass()))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            cands.append((idx, "CALL", "call->pass", lambda n: ast.Pass()))
        if isinstance(node, ast.Call):
            pos = node.args
            if len(pos) >= 2 and not any(isinstance(a, ast.Starred) for a in pos[:2]):
                cands.append((idx, "ARG", "swap args 0,1", _swap_args))
    return cands


def _replace_in_parent(root: ast.AST, target: ast.AST, new: ast.AST) -> None:
    for parent in ast.walk(root):
        for field, value in ast.iter_fields(parent):
            if value is target:
                setattr(parent, field, new)
                return
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if item is target:
                        value[i] = new
                        return


def _apply(tree: ast.Module, idx: int, fn: _Mut) -> str:
    clone = copy.deepcopy(tree)
    target = list(ast.walk(clone))[idx]
    new = fn(target)
    if new is not target:
        if hasattr(target, "lineno") and not hasattr(new, "lineno"):
            ast.copy_location(new, target)
        _replace_in_parent(clone, target, new)
    ast.fix_missing_locations(clone)
    return ast.unparse(clone)


def _in_scope(line: int, scope: Scope | None) -> bool:
    return scope is None or any(a <= line <= b for a, b in scope)


def _diff_snippet(a: str, b: str) -> str:
    """First differing line of the mutated module (readable change summary)."""

    la, lb = a.splitlines(), b.splitlines()
    for x, y in zip(la, lb, strict=False):
        if x != y:
            return y.strip()
    if len(lb) < len(la):
        return f"<removed: {la[len(lb)].strip()}>"
    return lb[len(la)].strip() if len(lb) > len(la) else ""


def generate_mutants(
    source: str,
    path: str,
    scope: Iterable[tuple[int, int]] | None = None,
    operators: Iterable[str] = OPERATOR_IDS,
) -> list[Mutant]:
    """Return deterministically ordered, de-duplicated mutants of ``source``.

    Mutants whose module text equals the unparsed original (no-ops) are dropped.
    Unparseable source yields ``[]``. ``scope=None`` mutates the whole file.
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    enabled = set(operators)
    scope_t: Scope | None = None if scope is None else tuple(scope)
    pragma = _pragma_lines(source)
    skip_const = _docstring_nodes(tree) | _fstring_constants(tree)
    quals = _qualnames(tree)
    baseline = ast.unparse(tree)
    nodes = list(ast.walk(tree))
    out: dict[str, Mutant] = {}
    for idx, op, desc, fn in _candidates(tree, skip_const):
        if op not in enabled:
            continue
        node = nodes[idx]
        line = getattr(node, "lineno", 0)
        if not _in_scope(line, scope_t) or line in pragma:
            continue
        mutated = _apply(tree, idx, fn)
        if mutated == baseline:
            continue
        col = node.col_offset  # type: ignore[attr-defined]
        end_line = getattr(node, "end_lineno", line) or line
        end_col = getattr(node, "end_col_offset", col) or col
        original = ast.get_source_segment(source, node) or ""
        replacement = _diff_snippet(baseline, mutated)
        mid = hashlib.sha1(  # noqa: S324 - identity hash, not security
            f"{path}|{op}|{line}|{col}|{end_line}|{end_col}|{desc}|{replacement}".encode()
        ).hexdigest()[:12]
        if mid in out:
            continue
        out[mid] = Mutant(
            id=mid,
            path=path,
            operator=op,
            lineno=line,
            col=col,
            end_lineno=end_line,
            end_col=end_col,
            original=original,
            replacement=replacement,
            symbol=_symbol_at(quals, line),
            mutated_source=mutated,
            mutant_hash=hashlib.sha256(mutated.encode()).hexdigest(),
            description=desc,
        )
    return sorted(
        out.values(),
        key=lambda m: (m.path, m.lineno, m.col, m.operator, m.replacement, m.id),
    )
