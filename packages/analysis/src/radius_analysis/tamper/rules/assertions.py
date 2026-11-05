"""Assertion rules: T003 removed, T004 weakened, T005 tautological, T006 expected changed."""

from __future__ import annotations

import re
from collections import Counter

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import Assertion, intersects
from radius_analysis.tamper.rules._common import (
    PairedTest,
    align,
    enclosing_test,
    pairs,
    test_id,
    test_views,
)
from radius_analysis.tamper.rules.base import BaseRule

_COMMENTED_ASSERT = re.compile(
    r"^\s*#\s*(assert\b|self\.assert\w+\(|with\s+pytest\.raises|pytest\.raises\()"
)


def _norm(line: str) -> str:
    return " ".join(line.split())


class AssertionRemoved(BaseRule):
    id = "T003"
    family = Family.ASSERTION_WEAKENING
    checks = {
        "assertion_removed": CheckSpec(Severity.HIGH, "fewer assertions in an existing test"),
        "body_emptied": CheckSpec(Severity.HIGH, "test body reduced to pass / ... / docstring"),
        "commented_out_assertion": CheckSpec(Severity.HIGH, "an assertion was commented out"),
    }
    doc = RuleDoc(
        title="Assertion removed",
        rationale="A test that asserts less proves less; removing assertions keeps the test "
        "green while the behavior it used to pin is no longer checked.",
        example_before="def test_total():\n    assert total([1, 2]) == 3\n    assert total([]) == 0",
        example_after="def test_total():\n    assert total([1, 2]) == 3",
        limitations="Assertions moved to another test of the same PR are not reported; "
        "legitimate consolidation of parametrized tests can look the same (confidence 0.7).",
        maps_to="T003",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        head_keys: set[str] = set()
        for view in test_views(context):
            mod = context.tests_of(view, "head")
            if mod:
                head_keys.update(a.key for fn in mod.tests.values() for a in fn.assertions)
        for view in test_views(context):
            head_mod = context.tests_of(view, "head")
            for p in pairs(context, view):
                out.extend(self._pair(context, p, head_keys))
            out.extend(self._commented(context, view, head_mod))
        return out

    def _pair(self, ctx: TamperContext, p: PairedTest, head_keys: set[str]) -> list[Finding]:
        if p.base is None or p.head is None:
            return []
        b, h = p.base, p.head
        tid = test_id(p.view.path, p.qualname)
        if h.emptied and not b.emptied:
            return [ctx.finding(
                self, "body_emptied", p.view.path,
                f"test `{p.qualname}` had {len(b.assertions)} assertion(s) and now has an empty body "
                "(pass / ... / docstring only), so it passes without checking anything",
                symbol=p.qualname, test_id=tid, old_range=(b.start, b.end), new_range=(h.start, h.end),
                old=b.text, new=h.text, confidence=0.95,
            )]
        if len(h.assertions) >= len(b.assertions) or not b.assertions:
            return []
        remaining = Counter(a.key for a in h.assertions)
        lost = []
        for a in b.assertions:
            if remaining[a.key] > 0:
                remaining[a.key] -= 1
            elif a.key not in head_keys:
                lost.append(a)
        if not lost:
            return []
        first = lost[0]
        return [ctx.finding(
            self, "assertion_removed", p.view.path,
            f"test `{p.qualname}` lost {len(lost)} assertion(s) "
            f"({len(b.assertions)} -> {len(h.assertions)}); first removed: `{first.text}`",
            symbol=p.qualname, test_id=tid, old_range=(first.start, first.end),
            new_range=(h.start, h.end), old=first.text, new=None, confidence=0.8,
        )]

    def _commented(self, ctx: TamperContext, view, head_mod) -> list[Finding]:  # noqa: ANN001
        base_comments = {_norm(t) for t in view.base_lines() if _COMMENTED_ASSERT.match(t)}
        out = []
        for n, text in sorted(view.added.items()):
            if _COMMENTED_ASSERT.match(text) and _norm(text) not in base_comments:
                fn = enclosing_test(head_mod, n)
                if fn is None:
                    continue  # commented-out test bodies are reported by T001
                out.append(ctx.finding(
                    self, "commented_out_assertion", view.path,
                    f"assertion `{text.strip().lstrip('#').strip()}` was commented out",
                    symbol=fn.qualname, test_id=test_id(view.path, fn.qualname),
                    new_range=(n, n), new=text, confidence=0.85,
                ))
        return out


class AssertionWeakened(BaseRule):
    id = "T004"
    family = Family.ASSERTION_WEAKENING
    checks = {
        "tolerance_widened": CheckSpec(Severity.HIGH, "approx/almost-equal tolerance increased"),
        "conjunct_dropped": CheckSpec(Severity.HIGH, "one clause of an `and` assertion dropped"),
        "strength_reduced": CheckSpec(
            Severity.HIGH, "assertion replaced by a weaker kind (exact -> is not None, ...)"
        ),
    }
    doc = RuleDoc(
        title="Assertion weakened",
        rationale="Replacing an exact check by membership, ordering, `is not None` or plain "
        "truthiness (or widening a tolerance) lets wrong values pass.",
        example_before="assert reserve(10, 3) == 7",
        example_after="assert reserve(10, 3) is not None",
        limitations="Pairs assertions by position inside a test; a rewritten test with unrelated "
        "assertions is reported with lower confidence (0.6). Does not judge whether the new "
        "check is semantically equivalent.",
        maps_to="T004",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in test_views(context):
            for p in pairs(context, view):
                if p.base is None or p.head is None:
                    continue
                for b, h in align(p.base.assertions, p.head.assertions):
                    if b is None or h is None or b.key == h.key or h.kind == "tautology":
                        continue
                    f = self._compare(context, p, b, h)
                    if f:
                        out.append(f)
        return out

    def _compare(self, ctx: TamperContext, p: PairedTest, b: Assertion, h: Assertion) -> Finding | None:
        check = None
        reason = ""
        if b.kind == "approx" and h.kind == "approx" and b.tolerance and h.tolerance:
            if h.tolerance[0] > b.tolerance[0] or h.tolerance[1] > b.tolerance[1]:
                check = "tolerance_widened"
                reason = (f"tolerance widened from rel={b.tolerance[0]:g}, abs={b.tolerance[1]:g} "
                          f"to rel={h.tolerance[0]:g}, abs={h.tolerance[1]:g}")
        if check is None and h.strength < b.strength and b.kind != "raises" and h.kind != "raises":
            check = "strength_reduced"
            reason = f"{b.kind} check weakened to {h.kind} check"
        if (
            check is None
            and h.conjuncts < b.conjuncts
            and h.strength <= b.strength
            # `assert a and b` split into `assert a` / `assert b` keeps every clause: compare the
            # clause totals of the whole test, not just the positionally paired assertion.
            and sum(a.conjuncts for a in p.head.assertions) < sum(a.conjuncts for a in p.base.assertions)
        ):
            check = "conjunct_dropped"
            reason = f"assertion lost {b.conjuncts - h.conjuncts} clause(s) of an `and` chain"
        if check is None:
            return None
        related = (b.callee is not None and b.callee == h.callee) or b.text.split()[0:1] == h.text.split()[0:1]
        assert p.head is not None
        return ctx.finding(
            self, check, p.view.path,
            f"in `{p.qualname}`: `{b.text}` -> `{h.text}`: {reason}",
            symbol=p.qualname, test_id=test_id(p.view.path, p.qualname),
            old_range=(b.start, b.end), new_range=(h.start, h.end), old=b.text, new=h.text,
            confidence=0.9 if related else 0.6,
        )


class Tautology(BaseRule):
    id = "T005"
    family = Family.TAUTOLOGY
    checks = {
        "always_true": CheckSpec(Severity.HIGH, "assertion that can never fail (`assert True`)"),
        "self_comparison": CheckSpec(Severity.HIGH, "an expression compared with itself"),
    }
    doc = RuleDoc(
        title="Tautological assertion",
        rationale="`assert True`, `assert x == x` and similar can never fail, so the test "
        "contributes no evidence while looking like a passing check.",
        example_before="assert reserve(5, 5) == 0",
        example_after="assert reserve(5, 5) == reserve(5, 5)",
        limitations="Only assertions on added or changed lines are reported. Idempotence or "
        "determinism checks (`f(x) == f(x)`) are legitimate in rare cases; they carry "
        "confidence 0.8, plain constants 0.95.",
        maps_to="T005",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in test_views(context):
            base_keys: set[str] = set()
            base_mod = context.tests_of(view, "base")
            if base_mod:
                base_keys = {a.key for fn in base_mod.tests.values() for a in fn.assertions}
            head_mod = context.tests_of(view, "head")
            if head_mod is None:
                continue
            for fn in head_mod.tests.values():
                for a in fn.assertions:
                    if a.kind != "tautology" or a.key in base_keys:
                        continue
                    if not intersects(a.start, a.end, view.added):
                        continue
                    check = "self_comparison" if "itself" in (a.tautology or "") else "always_true"
                    conf = 0.8 if check == "self_comparison" and "(" in a.text else 0.95
                    out.append(context.finding(
                        self, check, view.path,
                        f"in `{fn.qualname}`: `{a.text}` can never fail: {a.tautology}",
                        symbol=fn.qualname, test_id=test_id(view.path, fn.qualname),
                        new_range=(a.start, a.end), new=a.text, confidence=conf,
                    ))
        return out


class ExpectedValueChanged(BaseRule):
    id = "T006"
    family = Family.EXPECTED_VALUE_CHANGE
    checks = {
        "expected_literal_changed": CheckSpec(
            Severity.MEDIUM, "expected literal edited while the code under test also changed"
        ),
        "snapshot_updated": CheckSpec(
            Severity.MEDIUM, "snapshot / golden file edited alongside source behavior changes"
        ),
    }
    doc = RuleDoc(
        title="Expected value changed with the code under test",
        rationale="When a test's expected value is edited in the same PR that changes the code "
        "it exercises, the test may have been bent to match new behavior instead of "
        "checking the intended behavior.",
        example_before="assert price(2) == 10   # price() also changes in this PR",
        example_after="assert price(2) == 12",
        limitations="Cannot know whether the new value is the intended one; justification must "
        "come from intent (EV-03/LK-02) or a waiver. Snapshot detection is path-convention "
        "based; unchanged-source PRs are never reported.",
        maps_to="T006",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        sut = context.behavioral_source_symbols()
        if not sut:
            return []
        names = {s.qualified_name.rsplit(".", 1)[-1] for s in sut}
        out: list[Finding] = []
        for view in test_views(context):
            for p in pairs(context, view):
                if p.base is None or p.head is None:
                    continue
                for b, h in align(p.base.assertions, p.head.assertions):
                    if b is None or h is None or b.key == h.key:
                        continue
                    if (b.kind in ("exact", "approx") and h.kind == b.kind and b.op == h.op
                            and b.callee and b.callee == h.callee and b.callee in names
                            and b.expected is not None and h.expected is not None
                            and b.expected != h.expected):
                        out.append(context.finding(
                            self, "expected_literal_changed", view.path,
                            f"in `{p.qualname}`: expected value of `{b.callee}(...)` changed "
                            f"`{b.expected}` -> `{h.expected}` while `{b.callee}` also changed "
                            "in this PR",
                            symbol=p.qualname, test_id=test_id(view.path, p.qualname),
                            old_range=(b.start, b.end), new_range=(h.start, h.end),
                            old=b.text, new=h.text, confidence=0.75,
                            evidence=(f"changed_symbol:{b.callee}",),
                        ))
        for view in context.views(Role.SNAPSHOT):
            if view.status.value == "modified" and view.removed:
                out.append(context.finding(
                    self, "snapshot_updated", view.path,
                    f"snapshot/golden file `{view.path}` was edited ({len(view.removed)} line(s) "
                    f"replaced) while {len(sut)} source symbol(s) changed behavior",
                    old_range=(min(view.removed), max(view.removed)),
                    new_range=(min(view.added), max(view.added)) if view.added else None,
                    old=next(iter(view.removed.values())),
                    new=next(iter(view.added.values()), None),
                    confidence=0.5,
                ))
        return out
