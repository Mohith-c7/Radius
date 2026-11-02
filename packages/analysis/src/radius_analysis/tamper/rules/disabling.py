"""Test-disabling rules: T001 deleted / removed cases, T002 skipped or xfailed."""

from __future__ import annotations

import ast
import re

from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import TestFn, unparse
from radius_analysis.tamper.rules._common import pairs, test_id, test_views
from radius_analysis.tamper.rules.base import BaseRule

_COMMENTED_TEST = re.compile(r"^\s*#\s*(async\s+)?def\s+(test\w*)\s*\(")


def _norm(line: str) -> str:
    return " ".join(line.split())


class DeletedTestRule(BaseRule):
    id = "T001"
    family = Family.TEST_DISABLING
    checks = {
        "test_deleted": CheckSpec(Severity.HIGH, "test removed while the code under test remains"),
        "parametrize_case_removed": CheckSpec(Severity.HIGH, "parametrize cases removed"),
        "commented_out_test": CheckSpec(Severity.HIGH, "test function commented out"),
    }
    doc = RuleDoc(
        title="Test deleted without removing the code under test",
        rationale="Deleting a failing test (or a parametrized case, or commenting it out) "
        "removes the evidence while the behavior it pinned is still shipped.",
        example_before="def test_rejects_zero():\n    with pytest.raises(ValueError):\n        reserve(1, 0)",
        example_after="# (test removed, reserve() still exists)",
        limitations="The code under test is inferred from the names the test calls; if every "
        "called name is a symbol removed in the same PR the deletion is treated as legitimate. "
        "Tests moved to another file with an identical body are not reported.",
        maps_to="T001",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        removed_names = context.removed_symbol_names()
        moved_keys = self._head_test_texts(context)
        for view in test_views(context):
            head_mod = context.tests_of(view, "head")
            commented = {
                m.group(2): (n, t)
                for n, t in view.added.items()
                if (m := _COMMENTED_TEST.match(t))
            }
            for n, t in sorted(view.added.items()):
                if _COMMENTED_TEST.match(t) and _norm(t) not in {_norm(x) for x in view.base_lines()}:
                    name = _COMMENTED_TEST.match(t).group(2)  # type: ignore[union-attr]
                    out.append(context.finding(
                        self, "commented_out_test", view.path,
                        f"test `{name}` was commented out",
                        symbol=name, test_id=test_id(view.path, name), new_range=(n, n), new=t,
                        confidence=0.9,
                    ))
            for p in pairs(context, view):
                if p.base is not None and p.head is None:
                    if p.base.name in commented or p.base.text in moved_keys:
                        continue
                    sut = p.base.called - {
                        q.rsplit(".", 1)[-1] for q in (head_mod.tests if head_mod else {})
                    }
                    if sut and sut <= removed_names:
                        continue
                    conf = 0.85 if sut else 0.5
                    out.append(context.finding(
                        self, "test_deleted", view.path,
                        f"test `{p.qualname}` was deleted"
                        + (f" while {', '.join(f'`{s}`' for s in sorted(sut))} still exist(s)"
                           if sut else ""),
                        symbol=p.qualname, test_id=test_id(view.path, p.qualname),
                        old_range=(p.base.start, p.base.end), old=p.base.text, confidence=conf,
                    ))
                elif p.base is not None and p.head is not None:
                    lost = list(p.base.param_cases)
                    for c in p.head.param_cases:
                        if c in lost:
                            lost.remove(c)
                    if lost and len(p.head.param_cases) < len(p.base.param_cases):
                        out.append(context.finding(
                            self, "parametrize_case_removed", view.path,
                            f"`{p.qualname}` lost {len(lost)} parametrize case(s): "
                            f"{', '.join(lost[:3])}",
                            symbol=p.qualname, test_id=test_id(view.path, p.qualname),
                            old_range=(p.base.start, p.base.end),
                            new_range=(p.head.start, p.head.end), old=lost[0], confidence=0.8,
                        ))
        return out

    @staticmethod
    def _head_test_texts(ctx: TamperContext) -> set[str]:
        texts: set[str] = set()
        for view in test_views(ctx):
            mod = ctx.tests_of(view, "head")
            if mod:
                texts.update(fn.text for fn in mod.tests.values())
        return texts


_SKIP_PATTERNS = (
    (re.compile(r"mark\.skipif\(|unittest\.skip(If|Unless)\(|^skip(If|Unless)\("), "skipif", 0.5),
    (re.compile(r"mark\.skip(\(|$)|unittest\.skip\(|^skip\(|^skip$"), "skip", 0.95),
    (re.compile(r"mark\.xfail|unittest\.expectedFailure|^expectedFailure$"), "xfail", 0.85),
)


def _label(deco: str) -> tuple[str, float] | None:
    text = deco.strip()
    for rx, label, conf in _SKIP_PATTERNS:
        if rx.search(text):
            return label, conf
    return None


def _skip_calls(fn: TestFn) -> set[str]:
    calls = set()
    for node in ast.walk(fn.node):
        if isinstance(node, ast.Call):
            text = unparse(node.func)
            if text in ("pytest.skip", "pytest.xfail", "self.skipTest", "unittest.SkipTest"):
                calls.add(unparse(node))
    for node in ast.walk(fn.node):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
            calls.add(f"if {unparse(node.test)}: ...")
    return calls


class SkippedTestRule(BaseRule):
    id = "T002"
    family = Family.TEST_DISABLING
    checks = {
        "skip": CheckSpec(Severity.HIGH, "skip marker / unittest.skip added"),
        "skipif": CheckSpec(Severity.MEDIUM, "conditional skip added"),
        "xfail": CheckSpec(Severity.HIGH, "xfail / expectedFailure added"),
        "runtime_skip": CheckSpec(Severity.HIGH, "pytest.skip()/xfail() or `if False` in the body"),
        "module_skip": CheckSpec(Severity.HIGH, "module-level pytestmark skip/xfail added"),
    }
    doc = RuleDoc(
        title="Test newly skipped or xfailed",
        rationale="A skipped or expected-failure test reports green/neutral while verifying "
        "nothing; it is the cheapest way to make a failing suite pass.",
        example_before="def test_rejects_non_positive():",
        example_after='@pytest.mark.skip(reason="flaky")\ndef test_rejects_non_positive():',
        limitations="`skipif` with a platform/version condition is often legitimate "
        "(severity medium, confidence 0.5). Skips that exist at base are not reported.",
        maps_to="T002",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in test_views(context):
            head_mod = context.tests_of(view, "head")
            base_mod = context.tests_of(view, "base")
            if head_mod is None:
                continue
            base_marks = set(base_mod.module_marks) if base_mod else set()
            for mark in head_mod.module_marks:
                lab = _label(mark)
                if mark not in base_marks and lab:
                    line = next((n for n, t in view.added.items() if "pytestmark" in t), 1)
                    out.append(context.finding(
                        self, "module_skip", view.path,
                        f"module-level `pytestmark = {mark}` disables every test in the file",
                        new_range=(line, line), new=f"pytestmark = {mark}", confidence=lab[1],
                    ))
            seen_class: set[tuple[str, str]] = set()
            for p in pairs(context, view):
                if p.head is None:
                    continue
                out.extend(self._fn(context, view, p.base, p.head, seen_class))
        return out

    def _fn(
        self, ctx: TamperContext, view: FileView, base: TestFn | None, head: TestFn,
        seen_class: set[tuple[str, str]],
    ) -> list[Finding]:
        out: list[Finding] = []
        base_decos = set(base.all_decorators) if base else set()
        for deco in head.decorators + head.class_decorators:
            lab = _label(deco)
            if lab is None or deco in base_decos:
                continue
            is_class = deco in head.class_decorators and deco not in head.decorators
            if is_class:
                key = (head.class_name or "", deco)
                if key in seen_class:
                    continue
                seen_class.add(key)
            label, conf = lab
            sym = (head.class_name or head.qualname) if is_class else head.qualname
            conf = conf if base else min(conf, 0.7)
            out.append(ctx.finding(
                self, label, view.path,
                f"`@{deco}` was added to {'class' if is_class else 'test'} `{sym}`; "
                "it no longer provides passing evidence",
                symbol=sym, test_id=test_id(view.path, sym),
                new_range=(head.start, head.start), new=f"@{deco}", confidence=conf,
            ))
        base_calls = _skip_calls(base) if base else set()
        for call in sorted(_skip_calls(head) - base_calls):
            out.append(ctx.finding(
                self, "runtime_skip", view.path,
                f"`{call}` was added to the body of `{head.qualname}`; the test can skip or "
                "never run its checks",
                symbol=head.qualname, test_id=test_id(view.path, head.qualname),
                new_range=(head.start, head.end), new=call, confidence=0.8,
            ))
        return out


__all__ = ["DeletedTestRule", "SkippedTestRule"]
