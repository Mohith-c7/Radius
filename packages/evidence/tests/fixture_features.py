"""Test-only helper: derive ``AssertionFeatures`` from the F-14 fixture test files.

A minimal AST classifier (a stand-in for LK-04, which lives in another package and
must not be imported here). It only has to be good enough to rank the fixture tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

from radius_evidence.domain.enums import AssertKind
from radius_evidence.domain.model import AssertionFact, AssertionFeatures

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"


def _is_call(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def classify(test: ast.expr) -> AssertKind:
    if _is_call(test, "isinstance"):
        return AssertKind.TYPE_CHECK
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, left, right = test.ops[0], test.left, test.comparators[0]
        if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant):
            # `is None` is a weak None check; `is True/False` pins an exact boolean
            return (
                AssertKind.NONE_CHECK
                if right.value is None
                else AssertKind.VALUE_EQUALITY
            )
        if isinstance(op, (ast.In, ast.NotIn)):
            return AssertKind.MEMBERSHIP
        if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            return AssertKind.COMPARISON_BOUND
        if isinstance(op, (ast.Eq, ast.NotEq)):
            if ast.dump(left) == ast.dump(right):
                return AssertKind.TAUTOLOGY
            if _is_call(left, "len"):
                return AssertKind.LENGTH_CHECK
            return AssertKind.VALUE_EQUALITY
    return AssertKind.TRUTHINESS


def features_for(path: Path, rel: str) -> dict[str, AssertionFeatures]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, AssertionFeatures] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test"):
            continue
        facts = [
            AssertionFact(classify(a.test), a.lineno, compares_computed_value=True)
            for a in ast.walk(node)
            if isinstance(a, ast.Assert)
        ]
        raises = any(
            isinstance(w, ast.With)
            and any("raises" in ast.dump(i.context_expr) for i in w.items)
            for w in ast.walk(node)
        )
        skip = any("skip" in ast.dump(d) for d in node.decorator_list)
        test_id = f"{rel}::{node.name}"
        out[test_id] = AssertionFeatures(
            test_id=test_id,
            path=rel,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            assertions=tuple(facts),
            n_assertions=len(facts),
            expects_exception=raises,
            is_parametrized=False,
            n_param_cases=None,
            has_skip_marker=skip,
            name_terms=(),
            literal_terms=(),
        )
    return out


def fixture_dirs() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if (p / "expected.json").is_file())


def all_features(fixture: Path) -> dict[str, AssertionFeatures]:
    out: dict[str, AssertionFeatures] = {}
    head = fixture / "head"
    for tf in sorted((head / "tests").glob("test_*.py")):
        out.update(features_for(tf, f"tests/{tf.name}"))
    return out
