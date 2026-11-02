"""T007: broad exception swallowing (tests and code) and over-broad ``pytest.raises``."""

from __future__ import annotations

import ast

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import TestFn, unparse
from radius_analysis.tamper.rules._common import pairs, test_id, test_views
from radius_analysis.tamper.rules.base import BaseRule

_BROAD = {"Exception", "BaseException"}


def _handler_type(h: ast.ExceptHandler) -> str:
    return "bare" if h.type is None else unparse(h.type)


def _swallows(h: ast.ExceptHandler) -> bool:
    for stmt in h.body:
        if isinstance(stmt, ast.Pass | ast.Continue):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Return) and (
            stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
        ):
            continue
        return False
    return True


def _handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]


class ExceptionSwallowRule(BaseRule):
    id = "T007"
    family = Family.EXCEPTION_SWALLOWING
    checks = {
        "test_swallow": CheckSpec(Severity.HIGH, "test catches broad exceptions and ignores them"),
        "swallows_assertion": CheckSpec(Severity.HIGH, "test catches AssertionError and ignores it"),
        "raises_broadened": CheckSpec(
            Severity.HIGH, "pytest.raises(SpecificError) broadened to Exception"
        ),
        "raises_broad": CheckSpec(Severity.MEDIUM, "new pytest.raises(Exception) in a test"),
        "source_broad_swallow": CheckSpec(
            Severity.MEDIUM, "new `except Exception: pass` in non-test code"
        ),
    }
    doc = RuleDoc(
        title="Broad exception swallow",
        rationale="`try/except: pass` around a test body (or `pytest.raises(Exception)`) makes "
        "a test pass whatever happens; in production code a swallowed exception hides failures "
        "the tests no longer see.",
        example_before="with pytest.raises(ValueError):\n    reserve(10, 0)",
        example_after="with pytest.raises(Exception):\n    reserve(10, 0)",
        limitations="Handlers that log, re-raise or assign are not reported. In non-test code "
        "only broad handlers with an empty body are reported (confidence 0.5).",
        maps_to="T007",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in test_views(context):
            out.extend(self._test_file(context, view))
        for view in context.views(Role.SOURCE, python_only=True):
            out.extend(self._source_file(context, view))
        return out

    def _new_handlers(self, ctx: TamperContext, view: FileView) -> list[ast.ExceptHandler]:
        head = ctx.tree_of(view, "head")
        if head is None:
            return []
        base = ctx.tree_of(view, "base")
        base_texts = {unparse(h) for h in _handlers(base)} if base else set()
        return [
            h for h in _handlers(head)
            if h.lineno in view.added and unparse(h) not in base_texts
        ]

    def _source_file(self, ctx: TamperContext, view: FileView) -> list[Finding]:
        out = []
        for h in self._new_handlers(ctx, view):
            if _handler_type(h) in _BROAD | {"bare"} and _swallows(h):
                out.append(ctx.finding(
                    self, "source_broad_swallow", view.path,
                    f"new `except {_handler_type(h)}` handler ignores the error",
                    new_range=(h.lineno, h.end_lineno or h.lineno), new=unparse(h), confidence=0.5,
                ))
        return out

    def _test_file(self, ctx: TamperContext, view: FileView) -> list[Finding]:
        out: list[Finding] = []
        head_mod = ctx.tests_of(view, "head")
        if head_mod is None:
            return out
        new_handlers = {id(h) for h in self._new_handlers(ctx, view)}
        for p in pairs(ctx, view):
            if p.head is None:
                continue
            fn: TestFn = p.head
            for h in _handlers(fn.node):
                if id(h) not in new_handlers or not _swallows(h):
                    continue
                kind = _handler_type(h)
                if kind in _BROAD | {"bare"}:
                    check = "test_swallow"
                elif kind == "AssertionError":
                    check = "swallows_assertion"
                else:
                    continue
                out.append(ctx.finding(
                    self, check, view.path,
                    f"in `{fn.qualname}`: `except {kind}` swallows the error, so the test "
                    "cannot fail on it",
                    symbol=fn.qualname, test_id=test_id(view.path, fn.qualname),
                    new_range=(h.lineno, h.end_lineno or h.lineno), new=unparse(h),
                    confidence=0.9,
                ))
            out.extend(self._raises(ctx, view, p.base, fn))
        return out

    def _raises(self, ctx: TamperContext, view: FileView, base: TestFn | None, head: TestFn) -> list[Finding]:
        def broad(fn: TestFn | None) -> list:
            return [a for a in (fn.assertions if fn else ()) if a.kind == "raises" and a.raises in _BROAD]

        head_broad = broad(head)
        base_broad = broad(base)
        if len(head_broad) <= len(base_broad):
            return []
        head_keys = {a.key for a in head.assertions}
        broadened = base is not None and any(
            a.kind == "raises" and a.raises not in _BROAD and a.key not in head_keys
            for a in base.assertions
        )
        added = [a for a in head_broad if a.key not in {b.key for b in base_broad}]
        a = added[0] if added else head_broad[-1]
        check = "raises_broadened" if broadened else "raises_broad"
        old = next((x.text for x in (base.assertions if base else ())
                    if x.kind == "raises" and x.raises not in _BROAD and x.key not in head_keys), None)
        return [ctx.finding(
            self, check, view.path,
            f"in `{head.qualname}`: " + (
                f"`{old}` was broadened to `{a.text}`" if broadened
                else f"`{a.text}` accepts any exception, so the test cannot pin the error type"),
            symbol=head.qualname, test_id=test_id(view.path, head.qualname),
            old_range=None, new_range=(a.start, a.end), old=old, new=a.text,
            confidence=0.9 if broadened else 0.6,
        )]
