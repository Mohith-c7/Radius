"""Deterministic AST mutation operators (seeded) for the real-repo benchmark."""
from __future__ import annotations

import ast
import random
from dataclasses import dataclass

CMP_FLIP = {ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
            ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
            ast.In: ast.NotIn, ast.NotIn: ast.In}
OPERATORS = ("flip_comparison", "negate_condition", "off_by_one", "return_none", "swap_add_sub")


@dataclass(frozen=True)
class Site:
    operator: str
    index: int  # n-th matching node in ast.walk order
    lineno: int


def _in_fstring(tree: ast.AST) -> set[int]:
    return {id(n) for js in ast.walk(tree) if isinstance(js, ast.JoinedStr) for n in ast.walk(js)}


def _sites_with_nodes(tree: ast.AST) -> list[tuple[Site, ast.AST]]:
    sites: list[tuple[Site, ast.AST]] = []
    counters = dict.fromkeys(OPERATORS, 0)
    skip = _in_fstring(tree)

    def add(op: str, node: ast.AST) -> None:
        if id(node) in skip:
            return
        sites.append((Site(op, counters[op], getattr(node, "lineno", 0)), node))
        counters[op] += 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in CMP_FLIP:
            add("flip_comparison", node)
        if isinstance(node, (ast.If, ast.While)):
            add("negate_condition", node)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            add("off_by_one", node)
        if isinstance(node, ast.Return) and node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            add("return_none", node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            add("swap_add_sub", node)
    return sites


def candidate_sites(source: str) -> list[Site]:
    return [s for s, _ in _sites_with_nodes(ast.parse(source))]


def _offset(lines: list[str], lineno: int, col: int) -> int:
    """Char offset of an AST (1-based line, UTF-8 byte column) position."""
    before = sum(len(ln) for ln in lines[: lineno - 1])
    return before + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8"))


def _splice(source: str, node: ast.AST, text: str) -> str:
    lines = source.splitlines(keepends=True)
    a = _offset(lines, node.lineno, node.col_offset)
    b = _offset(lines, node.end_lineno, node.end_col_offset)
    return source[:a] + text + source[b:]


def _find(tree: ast.AST, site: Site) -> ast.AST:
    for s, node in _sites_with_nodes(tree):
        if s.operator == site.operator and s.index == site.index:
            return node
    raise ValueError(f"site not found: {site}")


def apply(source: str, site: Site) -> str:
    """Apply one mutation as a minimal textual splice (rest of file byte-identical)."""
    tree = ast.parse(source)
    node = _find(tree, site)
    seg = ast.get_source_segment(source, node)
    op = site.operator
    if op == "flip_comparison":
        node.ops[0] = CMP_FLIP[type(node.ops[0])]()
        out = _splice(source, node, "(" + ast.unparse(node) + ")")
    elif op == "negate_condition":
        out = _splice(source, node.test, "not (" + ast.get_source_segment(source, node.test) + ")")
    elif op == "off_by_one":
        out = _splice(source, node, repr(node.value + 1))
    elif op == "return_none":
        out = _splice(source, node.value, "None")
    elif op == "swap_add_sub":
        node.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
        out = _splice(source, node, "(" + ast.unparse(node) + ")")
    else:  # pragma: no cover
        raise ValueError(op)
    assert seg is not None
    ast.parse(out)  # mutant must remain syntactically valid
    return out


def sample(files: dict[str, str], n: int, seed: int) -> list[tuple[str, Site]]:
    """Pick n (file, site) pairs deterministically from all candidate sites."""
    pool = [(path, s) for path in sorted(files) for s in candidate_sites(files[path])]
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[:n]
