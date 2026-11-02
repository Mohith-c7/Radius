"""Test-disabling rules: T001 deleted / removed cases, T002 skipped or xfailed."""

from __future__ import annotations

import ast
import difflib
import re

from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import TestFn, unparse
from radius_analysis.tamper.rules._common import pairs, test_id, test_views
from radius_analysis.tamper.rules.base import BaseRule

_COMMENTED_TEST = re.compile(r"^\s*#\s*(async\s+)?def\s+(test\w*)\s*\(")
_DEF_NAME = re.compile(r"\b(async\s+def|def)\s+\w+")

#: A deleted test whose body is at least this similar (name ignored) to a test added in the
#: same PR is a rename or move, not a deletion (replay 2026-11, finding F-T1).
RENAME_SIMILARITY = 0.6


def _norm(line: str) -> str:
    return " ".join(line.split())


def _body_key(fn: TestFn) -> str:
    """Test source with the function name blanked and whitespace collapsed."""

    return _norm(_DEF_NAME.sub(r"\1 _", fn.text, count=1))


def _is_rename_of(deleted: TestFn, pool: list[tuple[str, TestFn]]) -> bool:
    """Consume and return True when an added test looks like ``deleted`` renamed or moved.

    A candidate must keep assertions when the deleted test had any (an emptied copy is a
    weakening, not a rename). Each added test explains at most one deleted test."""

    key = _body_key(deleted)
    best: tuple[float, int] | None = None
    for i, (_path, cand) in enumerate(pool):
        if deleted.assertions and not cand.assertions:
            continue
        if deleted.called and len(deleted.called & cand.called) / len(deleted.called | cand.called) < 0.5:
            continue  # a rename keeps calling the same code under test
        ratio = difflib.SequenceMatcher(None, key, _body_key(cand), autojunk=False).ratio()
        if ratio >= RENAME_SIMILARITY and (best is None or ratio > best[0]):
            best = (ratio, i)
    if best is None:
        return False
    del pool[best[1]]
    return True


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
        "Tests moved to another file with an identical body, and tests renamed or moved with "
        "a body at least 60% similar to a test added in the same PR (name ignored, assertions "
        "kept), are not reported; a deliberate rename plus weakening below that similarity "
        "is still a deletion.",
        maps_to="T001",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        removed_names = context.removed_symbol_names()
        moved_keys = self._head_test_texts(context)
        added_pool = self._added_tests(context)
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
                    if _is_rename_of(p.base, added_pool):
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
    def _added_tests(ctx: TamperContext) -> list[tuple[str, TestFn]]:
        """Tests present at head with no base counterpart (candidates for a rename target)."""

        out: list[tuple[str, TestFn]] = []
        for view in test_views(ctx):
            out.extend(
                (view.path, p.head)
                for p in pairs(ctx, view)
                if p.base is None and p.head is not None
            )
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


_SKIP_FUNCS = ("pytest.skip", "pytest.xfail", "self.skipTest", "unittest.SkipTest")

#: Conditions that look at the environment (platform, env vars, installed packages, files,
#: tool availability). A skip under one of these is a guard, not a disabled test.
_ENV_GUARD = re.compile(
    r"sys\.platform|\bplatform\b|os\.name|os\.environ|getenv|version_info|find_spec|importlib"
    r"|import_module|importorskip|which\(|\.exists\(|\.is_file\(|\.is_dir\(|isfile|isdir"
    r"|installed|available|_HAS_|HAVE_|\bhas_\w+|returncode|\bis None\b",
    re.IGNORECASE,
)
_ENV_EXCEPTIONS = {
    "ImportError", "ModuleNotFoundError", "OSError", "FileNotFoundError", "EnvironmentError",
    "subprocess.CalledProcessError", "CalledProcessError",
}


def _guard_of(ancestors: list[ast.AST]) -> str:
    """Return an empty string (unconditional), "env" (environment guard) or "cond"."""

    kind = ""
    for node in ancestors:
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Constant) and not test.value:
                continue  # `if False:` is the disabling pattern, not a guard
            if _ENV_GUARD.search(unparse(test)):
                return "env"
            kind = "cond"
        elif isinstance(node, ast.ExceptHandler):
            names: list[str] = []
            if isinstance(node.type, ast.Tuple):
                names = [unparse(e) for e in node.type.elts]
            elif node.type is not None:
                names = [unparse(node.type)]
            if names and all(n in _ENV_EXCEPTIONS for n in names):
                return "env"
            kind = "cond"
    return kind


def _walk_with_ancestors(node: ast.AST, ancestors: tuple[ast.AST, ...] = ()):  # noqa: ANN202
    yield node, ancestors
    for child in ast.iter_child_nodes(node):
        yield from _walk_with_ancestors(child, (*ancestors, node))


def _skip_calls(fn: TestFn) -> dict[str, str]:
    """Runtime skip call (or ``if False``) text -> guard kind (see ``_guard_of``)."""

    calls: dict[str, str] = {}
    for node, ancestors in _walk_with_ancestors(fn.node):
        if isinstance(node, ast.Call) and unparse(node.func) in _SKIP_FUNCS:
            text = unparse(node)
            guard = _guard_of(list(ancestors))
            if text not in calls or not guard:  # the strictest reading wins
                calls[text] = guard
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
            calls[f"if {unparse(node.test)}: ..."] = ""
    return calls


class SkippedTestRule(BaseRule):
    id = "T002"
    family = Family.TEST_DISABLING
    checks = {
        "skip": CheckSpec(Severity.HIGH, "skip marker / unittest.skip added"),
        "skipif": CheckSpec(Severity.MEDIUM, "conditional skip added"),
        "xfail": CheckSpec(Severity.HIGH, "xfail / expectedFailure added"),
        "runtime_skip": CheckSpec(
            Severity.HIGH,
            "unconditional pytest.skip()/xfail() or `if False` added to a test that existed",
        ),
        "runtime_skip_new": CheckSpec(
            Severity.MEDIUM, "unconditional pytest.skip()/xfail() in a test new in this PR"
        ),
        "runtime_skip_conditional": CheckSpec(
            Severity.MEDIUM, "pytest.skip()/xfail() under a non-environment condition"
        ),
        "runtime_skip_guarded": CheckSpec(
            Severity.LOW,
            "pytest.skip() under an environment guard (platform, env var, optional import, file)",
        ),
        "module_skip": CheckSpec(Severity.HIGH, "module-level pytestmark skip/xfail added"),
    }
    doc = RuleDoc(
        title="Test newly skipped or xfailed",
        rationale="A skipped or expected-failure test reports green/neutral while verifying "
        "nothing; it is the cheapest way to make a failing suite pass.",
        example_before="def test_rejects_non_positive():",
        example_after='@pytest.mark.skip(reason="flaky")\ndef test_rejects_non_positive():',
        limitations="`skipif` with a platform/version condition is often legitimate "
        "(severity medium, confidence 0.5). Skips that exist at base are not reported. A "
        "runtime skip under an `if` on the platform, environment, installed packages or files, "
        "or in an `except ImportError`-style handler, is `runtime_skip_guarded` (low); only an "
        "unconditional skip added to a test that already existed is high. The guard is "
        "recognised textually, so a skip hidden behind an innocent-looking environment "
        "condition is reported low.",
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
        base_calls = _skip_calls(base) if base else {}
        head_calls = _skip_calls(head)
        for call in sorted(set(head_calls) - set(base_calls)):
            guard = head_calls[call]
            if guard == "env":
                check, conf, note = "runtime_skip_guarded", 0.6, "under an environment guard"
            elif guard == "cond":
                check, conf, note = "runtime_skip_conditional", 0.6, "under a condition"
            elif base is None:
                check, conf, note = "runtime_skip_new", 0.7, "unconditionally, in a new test"
            else:
                check, conf, note = "runtime_skip", 0.8, "unconditionally"
            out.append(ctx.finding(
                self, check, view.path,
                f"`{call}` was added {note} to the body of `{head.qualname}`; the test can skip "
                "or never run its checks",
                symbol=head.qualname, test_id=test_id(view.path, head.qualname),
                new_range=(head.start, head.end), new=call, confidence=conf,
            ))
        return out


__all__ = ["DeletedTestRule", "SkippedTestRule"]
