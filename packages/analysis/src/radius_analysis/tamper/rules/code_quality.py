"""Changed-line code rules: T013 suppressions, T014 stubs, T015 security downgrades, T016 debug."""

from __future__ import annotations

import ast
import re

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.pyast import is_stub_body, unparse
from radius_analysis.tamper.rules.base import BaseRule

_SUPPRESSIONS = (
    ("noqa", re.compile(r"#\s*noqa\b(?::\s*([A-Z0-9, ]+))?", re.IGNORECASE)),
    ("type_ignore", re.compile(r"#\s*type:\s*ignore(?:\[([^\]]*)\])?")),
    ("type_ignore", re.compile(r"#\s*pyright:\s*ignore")),
    ("lint_disable", re.compile(r"#\s*pylint:\s*disable")),
    ("nosec", re.compile(r"#\s*nosec\b")),
    ("ts_ignore", re.compile(r"//\s*@ts-(?:ignore|nocheck)|eslint-disable(?!-next-line\s*$)")),
)
_BENIGN_NOQA = {"F401", "E402", "E501", "I001"}
_SUPPRESS_LANGS = (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _code_added(view: FileView) -> dict[int, str]:
    return {n: t for n, t in view.added.items() if t.strip() and not t.strip().startswith("#")}


class SuppressionRule(BaseRule):
    id = "T013"
    family = Family.SUPPRESSION
    checks = {
        "noqa": CheckSpec(Severity.LOW, "`# noqa` added"),
        "type_ignore": CheckSpec(Severity.LOW, "`# type: ignore` added"),
        "lint_disable": CheckSpec(Severity.LOW, "`# pylint: disable` added"),
        "nosec": CheckSpec(Severity.MEDIUM, "`# nosec` added (security linter silenced)"),
        "ts_ignore": CheckSpec(Severity.LOW, "`@ts-ignore` / `eslint-disable` added"),
    }
    languages = frozenset({"python", "typescript", "javascript"})
    doc = RuleDoc(
        title="Lint / type suppression added",
        rationale="A suppression marker on a changed line silences the checker that would have "
        "flagged it. One is routine; a pattern of them is how type or lint gates get bypassed.",
        example_before="value = parse(raw)",
        example_after="value = parse(raw)  # type: ignore",
        limitations="Benign idioms are skipped: `# noqa` limited to F401/E402/E501/I001 and "
        "`type: ignore[import...]`. Marker detection is textual and can match inside strings. "
        "Use `params.min_added_suppressions` to report only above a PR-wide count. Several "
        "suppressions of the same kind in one file are reported as one summarized finding "
        "(with the line numbers), never as one finding per line; severity is that of the "
        "check and does not grow with the count.",
        maps_to="T013",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        hits: list[tuple[FileView, int, str, str, str]] = []
        for view in context.views():
            if not view.path.endswith(_SUPPRESS_LANGS):
                continue
            base = {_norm(t) for t in view.base_lines()}
            for n, t in sorted(view.added.items()):
                if _norm(t) in base:
                    continue
                for check, rx in _SUPPRESSIONS:
                    m = rx.search(t)
                    if m and not self._benign(check, m, t):
                        hits.append((view, n, t, check, m.group(0)))
                        break
        if len(hits) < context.config.params.min_added_suppressions:
            return []
        # One finding per (file, check): a file with many `# noqa` lines is one finding that
        # says how many, not a wall of identical low findings (replay 2026-11, F-T3). The
        # severity is that of the check (low, `nosec` medium); it is never raised by counting.
        groups: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
        order: list[tuple[str, str]] = []
        for view, n, text, check, marker in hits:
            key = (view.path, check)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((n, text, marker))
        out: list[Finding] = []
        for path, check in order:
            items = groups[(path, check)]
            first_n, first_text, first_marker = items[0]
            if len(items) == 1:
                out.append(context.finding(
                    self, check, path,
                    f"`{first_marker}` suppresses a checker on a changed line",
                    new_range=(first_n, first_n), new=first_text, confidence=0.9,
                ))
                continue
            lines = [n for n, _t, _m in items]
            out.append(context.finding(
                self, check, path,
                f"{len(items)} `{first_marker}`-style suppressions were added in this file "
                f"(lines {', '.join(str(n) for n in lines[:5])}"
                f"{', ...' if len(lines) > 5 else ''})",
                new_range=(min(lines), max(lines)), new=first_text, confidence=0.9,
                evidence=tuple(f"line {n}: {' '.join(t.split())[:120]}" for n, t, _m in items[:5]),
            ))
        return out

    @staticmethod
    def _benign(check: str, m: re.Match[str], line: str) -> bool:
        if check == "noqa" and m.group(1):
            codes = {c.strip().upper() for c in m.group(1).split(",") if c.strip()}
            return bool(codes) and codes <= _BENIGN_NOQA
        if check == "type_ignore" and m.groups() and m.group(1):
            return m.group(1).startswith("import")
        return False


def _is_abstractish(fn: ast.FunctionDef | ast.AsyncFunctionDef, cls: ast.ClassDef | None) -> bool:
    decos = " ".join(unparse(d) for d in fn.decorator_list)
    if re.search(r"abstractmethod|overload|abstractproperty", decos):
        return True
    if cls is not None:
        bases = " ".join(unparse(b) for b in cls.bases)
        if re.search(r"Protocol|ABC|Exception|Error", bases):
            return True
    return False


def _stub_kind(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = fn.body
    if is_stub_body(body):
        return True
    if len(body) == 1 or (len(body) == 2 and is_stub_body(body[:1])):
        last = body[-1]
        if isinstance(last, ast.Raise) and last.exc is not None:
            target = last.exc.func if isinstance(last.exc, ast.Call) else last.exc
            return unparse(target) == "NotImplementedError"
        if isinstance(last, ast.Return) and (
            last.value is None or (isinstance(last.value, ast.Constant) and last.value.value is None)
        ):
            return unparse(fn.returns) != "None" if fn.returns is not None else True
    return False


def _functions(tree: ast.AST) -> dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
    out: dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]] = {}

    def visit(node: ast.AST, prefix: str, cls: ast.ClassDef | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", child)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                out[f"{prefix}{child.name}"] = (child, _is_abstractish(child, cls))
                visit(child, f"{prefix}{child.name}.", None)
            else:
                visit(child, prefix, cls)

    visit(tree, "", None)
    return out


class StubbedImplementationRule(BaseRule):
    id = "T014"
    family = Family.CODE_QUALITY
    checks = {
        "body_stubbed": CheckSpec(Severity.MEDIUM, "implemented function reduced to a stub"),
        "new_stub": CheckSpec(Severity.LOW, "new non-abstract function with a stub body"),
    }
    doc = RuleDoc(
        title="Stubbed implementation",
        rationale="Replacing a real body by `pass`, `...`, `raise NotImplementedError` or "
        "`return None` makes tests that only check 'no crash' pass while the feature is gone.",
        example_before="def total(xs):\n    return sum(xs)",
        example_after="def total(xs):\n    raise NotImplementedError",
        limitations="Abstract methods, overloads, Protocol/ABC/exception classes and dunder "
        "methods are exempt. New stubs are weak evidence (confidence 0.45): placeholders for "
        "later work are common.",
        maps_to="T014",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views(Role.SOURCE, python_only=True):
            if view.path.endswith(".pyi"):
                continue
            head = context.tree_of(view, "head")
            if head is None:
                continue
            base = context.tree_of(view, "base")
            base_fns = _functions(base) if base else {}
            for qual, (fn, abstract) in sorted(_functions(head).items()):
                if abstract or (fn.name.startswith("__") and fn.name.endswith("__")):
                    continue
                if not _stub_kind(fn):
                    continue
                old = base_fns.get(qual)
                if old is not None:
                    if _stub_kind(old[0]) or unparse(old[0]) == unparse(fn):
                        continue
                    out.append(context.finding(
                        self, "body_stubbed", view.path,
                        f"`{qual}` had an implementation and is now a stub",
                        symbol=qual, old_range=(old[0].lineno, old[0].end_lineno or old[0].lineno),
                        new_range=(fn.lineno, fn.end_lineno or fn.lineno),
                        old=unparse(old[0]), new=unparse(fn), confidence=0.85,
                    ))
                elif base is not None or view.status.value == "added":
                    if fn.lineno in view.added:
                        out.append(context.finding(
                            self, "new_stub", view.path, f"new function `{qual}` is a stub",
                            symbol=qual, new_range=(fn.lineno, fn.end_lineno or fn.lineno),
                            new=unparse(fn), confidence=0.45,
                        ))
        return out


_SECRET = re.compile(
    r"(?i)\b\w*(password|passwd|secret|api_?key|token|private_key)\w*\s*=\s*[\"']([^\"'\s]{8,})[\"']"
)
_PLACEHOLDER = re.compile(r"(?i)xxx|example|change.?me|placeholder|dummy|test|<.*>|\$\{|\{\{|env")
_SECURITY = (
    ("tls_verify_disabled", re.compile(
        r"verify\s*=\s*False|_create_unverified_context|check_hostname\s*=\s*False|\bCERT_NONE\b"), 0.9),
    ("sql_interpolation", re.compile(
        r"\.execute(?:many)?\(\s*(?:f[\"']|[\"'][^\"']*[\"']\s*(?:%|\.format\())"), 0.6),
)


class SecurityDowngradeRule(BaseRule):
    id = "T015"
    family = Family.CODE_QUALITY
    checks = {
        "tls_verify_disabled": CheckSpec(Severity.HIGH, "TLS verification turned off"),
        "hardcoded_secret": CheckSpec(Severity.HIGH, "credential-like literal assigned in code"),
        "sql_interpolation": CheckSpec(Severity.HIGH, "SQL built by string interpolation"),
    }
    doc = RuleDoc(
        title="Security downgrade",
        rationale="Turning off TLS verification, hard-coding credentials or interpolating SQL "
        "are classic shortcuts that make a failing integration test pass at the cost of safety.",
        example_before="requests.get(url)",
        example_after="requests.get(url, verify=False)",
        limitations="Regex based and intentionally narrow, not a SAST replacement (use Semgrep/"
        "Bandit via SARIF, EV-01). Test files are skipped; placeholder-looking secrets are "
        "ignored.",
        maps_to="T015",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views(Role.SOURCE, python_only=True):
            base = {_norm(t) for t in view.base_lines()}
            for n, t in sorted(_code_added(view).items()):
                if _norm(t) in base:
                    continue
                for check, rx, conf in _SECURITY:
                    if rx.search(t):
                        out.append(context.finding(
                            self, check, view.path,
                            "security-relevant protection weakened on a changed line",
                            new_range=(n, n), new=t, confidence=conf,
                        ))
                m = _SECRET.search(t)
                if m and not _PLACEHOLDER.search(m.group(2)):
                    out.append(context.finding(
                        self, "hardcoded_secret", view.path,
                        "credential-like value assigned from a string literal",
                        new_range=(n, n), new=_SECRET.sub(lambda mm: mm.group(0).split("=")[0] + "= '***'", t),
                        confidence=0.5,
                    ))
        return out


_ENTRYPOINT_NAMES = {"__main__.py", "cli.py", "manage.py", "setup.py", "conftest.py"}
_DEBUG_CALLS = {
    "breakpoint": 0.95, "pdb.set_trace": 0.95, "ipdb.set_trace": 0.95, "print": 0.5,
    "pprint.pprint": 0.4,
}


class DebugArtifactRule(BaseRule):
    id = "T016"
    family = Family.CODE_QUALITY
    checks = {
        "debug_call": CheckSpec(Severity.LOW, "print / breakpoint / pdb left in library code"),
    }
    doc = RuleDoc(
        title="Debug artifacts left behind",
        rationale="Leftover prints and breakpoints indicate unreviewed exploratory edits; "
        "`breakpoint()` can hang CI.",
        example_before="def total(xs):\n    return sum(xs)",
        example_after="def total(xs):\n    print(xs)\n    return sum(xs)",
        limitations="Low severity. CLI entry points (`__main__.py`, `cli.py`, `scripts/`) and "
        "`if __name__ == '__main__'` blocks are exempt from the `print` check.",
        maps_to="T016",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views(Role.SOURCE, python_only=True):
            tree = context.tree_of(view, "head")
            if tree is None:
                continue
            name = view.path.rsplit("/", 1)[-1]
            cli_like = name in _ENTRYPOINT_NAMES or view.path.startswith("scripts/") \
                or "/scripts/" in view.path
            base = {_norm(t) for t in view.base_lines()}
            main_lines: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and "__name__" in unparse(node.test):
                    main_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
                if isinstance(node, ast.FunctionDef) and node.name == "main":
                    main_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call = unparse(node.func)
                conf = _DEBUG_CALLS.get(call)
                if conf is None or node.lineno not in view.added:
                    continue
                if call in ("print", "pprint.pprint") and (cli_like or node.lineno in main_lines):
                    continue
                text = view.head_lines()[node.lineno - 1] if node.lineno <= len(view.head_lines()) else call
                if _norm(text) in base:
                    continue
                out.append(context.finding(
                    self, "debug_call", view.path, f"`{call}(...)` left in library code",
                    new_range=(node.lineno, node.lineno), new=text, confidence=conf,
                ))
        return sorted(out, key=lambda f: f.sort_key())
