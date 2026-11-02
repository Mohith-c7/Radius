"""T017 (EV-02 extension): fixture / conftest tampering."""

from __future__ import annotations

import ast
import re

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import unparse
from radius_analysis.tamper.rules.base import BaseRule

_PATCHY = re.compile(
    r"\b(monkeypatch\.setattr|monkeypatch\.setitem|patch(\.object|\.dict)?\(|setattr\(|"
    r"MagicMock|Mock\(|mocker\.|pytest\.skip|skip\()"
)
_HOOKS = {
    "pytest_collection_modifyitems", "pytest_runtest_setup", "pytest_runtest_call",
    "pytest_runtest_makereport", "pytest_ignore_collect", "pytest_pyfunc_call",
    "pytest_generate_tests",
}
_HOOK_DISABLES = re.compile(r"add_marker|skip|xfail|deselect|items\[:\]|items\.clear|\.remove\(|return True")
_COLLECT_IGNORE = {"collect_ignore", "collect_ignore_glob"}


def _is_autouse(deco: ast.expr) -> bool:
    if not isinstance(deco, ast.Call) or "fixture" not in unparse(deco.func):
        return False
    return any(
        k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in deco.keywords
    )


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


class FixtureTamperRule(BaseRule):
    id = "T017"
    family = Family.FIXTURE_TAMPERING
    checks = {
        "autouse_patch": CheckSpec(
            Severity.HIGH, "new autouse fixture that patches/mocks/skips for every test"
        ),
        "collection_hook": CheckSpec(
            Severity.HIGH, "conftest hook or collect_ignore that deselects/skips tests"
        ),
        "conftest_changed_with_source": CheckSpec(
            Severity.LOW, "conftest code changed in a PR that also changes source behavior"
        ),
    }
    doc = RuleDoc(
        title="Fixture / conftest tampering",
        rationale="A shared fixture or conftest hook affects every test in scope: an autouse "
        "fixture that patches core functions, or a hook that skips items, disables checks "
        "far from the diff a reviewer reads.",
        example_before="# conftest.py (unchanged)",
        example_after="@pytest.fixture(autouse=True)\ndef _quiet(monkeypatch):\n"
        '    monkeypatch.setattr("app.core.validate", lambda *a: True)',
        limitations="EV-02 extension: not part of the DESIGN T001-T016 catalog. Name-based and "
        "syntactic; autouse fixtures that only set env vars are not reported. The "
        "`conftest_changed_with_source` check is a weak signal (confidence 0.35).",
        maps_to="extension",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        sut = context.behavioral_source_symbols()
        for view in context.views(Role.CONFTEST, Role.TEST, python_only=True):
            head = context.tree_of(view, "head")
            if head is None:
                continue
            base = context.tree_of(view, "base")
            base_funcs = _functions(base) if base else {}
            for name, fn in sorted(_functions(head).items()):
                old = base_funcs.get(name)
                text = unparse(fn)
                if old is not None and unparse(old) == text:
                    continue
                if any(_is_autouse(d) for d in fn.decorator_list):
                    already = (
                        old is not None
                        and any(_is_autouse(d) for d in old.decorator_list)
                        and bool(_PATCHY.search(unparse(old)))
                    )
                    if _PATCHY.search(text) and not already:
                        out.append(context.finding(
                            self, "autouse_patch", view.path,
                            f"autouse fixture `{name}` patches, mocks or skips for every test "
                            "in its scope",
                            symbol=name, new_range=(fn.lineno, fn.end_lineno or fn.lineno),
                            new=text, confidence=0.8,
                        ))
                if view.has(Role.CONFTEST) and name in _HOOKS and _HOOK_DISABLES.search(text):
                    if old is None or not _HOOK_DISABLES.search(unparse(old)):
                        out.append(context.finding(
                            self, "collection_hook", view.path,
                            f"conftest hook `{name}` can skip or deselect tests",
                            symbol=name, new_range=(fn.lineno, fn.end_lineno or fn.lineno),
                            new=text, confidence=0.7,
                        ))
            if view.has(Role.CONFTEST):
                out.extend(self._collect_ignore(context, view, base))
                out.extend(self._with_source(context, view, sut))
        return out

    def _collect_ignore(self, ctx: TamperContext, view: FileView, base: ast.AST | None) -> list[Finding]:
        head = ctx.tree_of(view, "head")
        base_texts = set()
        if base is not None:
            base_texts = {unparse(n) for n in ast.walk(base) if isinstance(n, ast.Assign)}
        out = []
        for n in ast.walk(head) if head else []:
            if (isinstance(n, ast.Assign) and unparse(n) not in base_texts and any(
                isinstance(t, ast.Name) and t.id in _COLLECT_IGNORE for t in n.targets
            ) and n.lineno in view.added):
                out.append(ctx.finding(
                    self, "collection_hook", view.path,
                    "conftest `collect_ignore` change excludes files from test collection",
                    new_range=(n.lineno, n.end_lineno or n.lineno), new=unparse(n), confidence=0.7,
                ))
        return out

    def _with_source(self, ctx: TamperContext, view: FileView, sut: list) -> list[Finding]:
        if view.status.value != "modified" or not sut:
            return []
        code = {n: t for n, t in view.added.items() if t.strip() and not t.strip().startswith("#")}
        if not code:
            return []
        return [ctx.finding(
            self, "conftest_changed_with_source", view.path,
            f"`{view.path}` changed ({len(code)} code line(s)) in the same PR as "
            f"{len(sut)} source behavior change(s); shared test setup may have been adapted "
            "to the new behavior",
            new_range=(min(code), max(code)), new=code[min(code)], confidence=0.35,
        )]
