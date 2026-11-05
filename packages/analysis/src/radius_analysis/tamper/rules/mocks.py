"""T008: the unit under test is mocked inside its own test."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from radius_analysis.tamper.context import TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import TestFn, unparse
from radius_analysis.tamper.rules._common import pairs, test_id, test_views
from radius_analysis.tamper.rules.base import BaseRule

_PATCH = {"patch", "mock.patch", "unittest.mock.patch", "mocker.patch"}
_PATCH_OBJECT = {"patch.object", "mock.patch.object", "unittest.mock.patch.object",
                 "mocker.patch.object"}
_SETATTR = {"monkeypatch.setattr", "mp.setattr"}
_MOCK_CTORS = {"Mock", "MagicMock", "AsyncMock", "create_autospec", "mock.Mock", "mock.MagicMock"}
_SPEC_KW = {"autospec", "spec", "spec_set", "new_callable"}


@dataclass(frozen=True, slots=True)
class PatchSite:
    target: str  # last dotted component of the patched name
    full: str
    spec: bool
    text: str
    line: int


def _str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def patch_sites(fn: TestFn) -> list[PatchSite]:
    sites = []
    for node in ast.walk(fn.node):
        if not isinstance(node, ast.Call):
            continue
        func = unparse(node.func)
        target: str | None = None
        if func in _PATCH:
            target = _str(node.args[0]) if node.args else None
        elif func in _PATCH_OBJECT:
            target = _str(node.args[1]) if len(node.args) > 1 else None
        elif func in _SETATTR:
            target = _str(node.args[0]) if node.args else None
            if target is None and len(node.args) > 1:
                target = _str(node.args[1])
        if not target:
            continue
        spec = any(k.arg in _SPEC_KW for k in node.keywords)
        sites.append(PatchSite(target.rsplit(".", 1)[-1], target, spec, unparse(node), node.lineno))
    return sites


def _mock_vars(fn: TestFn) -> set[str]:
    names = set()
    for node in ast.walk(fn.node):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if unparse(node.value.func) in _MOCK_CTORS:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


class MockedSutRule(BaseRule):
    id = "T008"
    family = Family.MOCK_ABUSE
    checks = {
        "patches_unit_under_test": CheckSpec(
            Severity.HIGH, "the function the test asserts on is patched in the same test"
        ),
        "asserts_on_mock": CheckSpec(
            Severity.HIGH, "assertion checks the return value of a Mock the test configured"
        ),
        "autospec_removed": CheckSpec(Severity.MEDIUM, "autospec/spec removed from a patch"),
    }
    doc = RuleDoc(
        title="Unit under test mocked in its own test",
        rationale="If the test replaces the function it asserts on (or asserts on a mock it "
        "configured itself), the assertion checks the mock, not the code.",
        example_before='@patch("shop.pricing.helper")\ndef test_total(m):\n    assert total(2) == 4',
        example_after='@patch("shop.pricing.total")\ndef test_total(m):\n    assert total(2) == 4',
        limitations="Name-based: the patched attribute name is compared with the names the test "
        "calls; it does not resolve imports, so same-named unrelated functions can false-"
        "positive. Only patches/assertions that are new in this PR are reported.",
        maps_to="T008",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in test_views(context):
            for p in pairs(context, view):
                if p.head is None:
                    continue
                head, base = p.head, p.base
                tid = test_id(view.path, p.qualname)
                base_sites = patch_sites(base) if base else []
                base_texts = {s.text for s in base_sites}
                asserted = {a.callee for a in head.assertions if a.callee}
                for site in patch_sites(head):
                    if site.text in base_texts:
                        continue
                    if site.target in asserted or site.target in head.called:
                        out.append(context.finding(
                            self, "patches_unit_under_test", view.path,
                            f"in `{p.qualname}`: `{site.text}` patches `{site.target}`, which the "
                            "test itself calls and asserts on",
                            symbol=p.qualname, test_id=tid, new_range=(site.line, site.line),
                            new=site.text, confidence=0.9 if site.target in asserted else 0.7,
                        ))
                for old in base_sites:
                    if old.spec and any(
                        s.full == old.full and not s.spec for s in patch_sites(head)
                    ):
                        out.append(context.finding(
                            self, "autospec_removed", view.path,
                            f"in `{p.qualname}`: patch of `{old.full}` no longer uses "
                            "autospec/spec, so signature drift is not caught",
                            symbol=p.qualname, test_id=tid, new_range=(head.start, head.end),
                            old=old.text, confidence=0.8,
                        ))
                base_keys = {a.key for a in (base.assertions if base else ())}
                mocks = _mock_vars(head)
                for a in head.assertions:
                    if a.key in base_keys:
                        continue
                    if (a.callee in mocks) or any(f"{m}.return_value" in a.text for m in mocks):
                        out.append(context.finding(
                            self, "asserts_on_mock", view.path,
                            f"in `{p.qualname}`: `{a.text}` asserts on a mock the test configured "
                            "itself",
                            symbol=p.qualname, test_id=tid, new_range=(a.start, a.end),
                            new=a.text, confidence=0.75,
                        ))
        return out
