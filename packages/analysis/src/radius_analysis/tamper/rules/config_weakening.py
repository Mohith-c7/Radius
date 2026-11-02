"""Config-level rules: T009 coverage, T010 CI / test-runner config, T011 retries and sleeps.

These are line-based on purpose: CI and tool configs span YAML, TOML, INI and Make, and the
rules only need "which lines were added/removed" plus the enclosing key.
"""

from __future__ import annotations

import re

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.rules.base import BaseRule

_KEY = re.compile(r"^\s*([A-Za-z_][\w.\-]*)\s*[=:]")
_SECTION = re.compile(r"^\s*\[+([^\]]+)\]+\s*$")
_PRAGMA = re.compile(r"#\s*pragma:\s*no\s*cover", re.IGNORECASE)
_FAIL_UNDER = re.compile(r"(?:fail_under|--cov-fail-under)\s*[=: ]\s*[\"']?(\d+(?:\.\d+)?)")
_TEST_TOOLS = re.compile(
    r"(?<![\w-])(pytest|py\.test|tox|nox|unittest|jest|vitest|mocha|mypy|ruff|flake8|pylint|"
    r"bandit|eslint|tsc|npm (?:run )?test|pnpm (?:run )?test|yarn test|make test|go test|"
    r"cargo test|coverage)(?![\w-])"
)
_OR_TRUE = re.compile(r"\|\|\s*(true|exit\s+0|:)\b|;\s*true\s*$")
_COV_SECTION_KEYS = {"omit", "exclude_lines", "exclude_also", "exclude", "include"}
_STRICT_FLAGS = ("--strict-markers", "--strict-config", "--strict ", "-Werror", "-W error")
_DESELECT = re.compile(r"--deselect\b|--ignore(?:-glob)?[= ]|\s-k\s+[\"']?not\b|\s-m\s+[\"']?not\b")
_LINT_OFF = re.compile(
    r"ignore_errors\s*=\s*true|ignore_missing_imports\s*=\s*true|"
    r"disallow_untyped_defs\s*=\s*false|check_untyped_defs\s*=\s*false|^\s*strict\s*=\s*false",
    re.IGNORECASE,
)
_RETRY_CI = re.compile(
    r"--reruns|rerunfailures|nick-fields/retry|\bretry\s*:\s*\d|\bretries\s*:\s*\d|"
    r"max[-_]attempts|retry-on|--retries",
    re.IGNORECASE,
)
_RETRY_TEST = re.compile(
    r"^\s*@(?:pytest\.mark\.)?flaky\b|^\s*@(?:\w+\.)*retry\b|\breruns?\s*=|"
    r"^\s*(?:import|from)\s+tenacity",
    re.IGNORECASE,
)
_SLEEP = re.compile(r"\b(?:time|asyncio)\.sleep\(|(?<![\w.])sleep\(")


def _norm(text: str) -> str:
    return " ".join(text.split())


def enclosing_key(lines: list[str], lineno: int) -> tuple[str, str]:
    """(section, key) the 1-based ``lineno`` belongs to, scanning upward."""
    key = ""
    section = ""
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        text = lines[i]
        m = _SECTION.match(text)
        if m and not text.startswith((" ", "\t")):
            section = m.group(1)
            break
        if not key and (k := _KEY.match(text)):
            key = k.group(1)
    return section, key


def _code_added(view: FileView) -> dict[int, str]:
    return {
        n: t for n, t in view.added.items()
        if t.strip() and not t.strip().startswith("#")
    }


def _base_norm(view: FileView) -> set[str]:
    return {_norm(t) for t in view.base_lines()}


def _tools(text: str | None) -> set[str]:
    found: set[str] = set()
    for line in (text or "").splitlines():
        if line.strip().startswith("#"):
            continue
        found.update(m.group(1) for m in _TEST_TOOLS.finditer(line))
    return found


class CoverageSuppressionRule(BaseRule):
    id = "T009"
    family = Family.CONFIG_WEAKENING
    languages = frozenset({"*"})
    checks = {
        "pragma_no_cover": CheckSpec(Severity.MEDIUM, "`# pragma: no cover` added"),
        "fail_under_lowered": CheckSpec(Severity.HIGH, "coverage fail-under threshold lowered or removed"),
        "omit_added": CheckSpec(Severity.MEDIUM, "coverage omit / exclude entry added"),
        "coverage_disabled": CheckSpec(Severity.HIGH, "--no-cov added or --cov removed"),
    }
    doc = RuleDoc(
        title="Coverage suppression",
        rationale="Coverage gates only protect when thresholds hold and code is measured; "
        "lowering `fail_under`, adding `omit` entries or `# pragma: no cover` hides untested "
        "code from the gate.",
        example_before="[tool.coverage.report]\nfail_under = 90",
        example_after="[tool.coverage.report]\nfail_under = 60",
        limitations="Section/key detection is textual (TOML/INI). Entries in `exclude_lines` "
        "are reported even when benign (e.g. `if TYPE_CHECKING:`), at medium severity.",
        maps_to="T009",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views():
            if view.is_python:
                base = _base_norm(view)
                for n, t in sorted(view.added.items()):
                    if _PRAGMA.search(t) and _norm(t) not in base:
                        out.append(context.finding(
                            self, "pragma_no_cover", view.path,
                            "`# pragma: no cover` hides this code from coverage",
                            new_range=(n, n), new=t, confidence=0.9,
                        ))
            if view.has(Role.BUILD_CONFIG, Role.CI_WORKFLOW, Role.MANIFEST):
                out.extend(self._config(context, view))
        return out

    def _config(self, ctx: TamperContext, view: FileView) -> list[Finding]:
        out: list[Finding] = []
        removed = [float(m.group(1)) for t in view.removed.values() for m in _FAIL_UNDER.finditer(t)]
        added = [float(m.group(1)) for t in view.added.values() for m in _FAIL_UNDER.finditer(t)]
        head_has = [float(m.group(1)) for m in _FAIL_UNDER.finditer(view.head_text or "")]
        if removed:
            threshold = max(removed)
            now = min(added) if added else (min(head_has) if head_has else None)
            if now is None or now < threshold:
                out.append(ctx.finding(
                    self, "fail_under_lowered", view.path,
                    f"coverage fail-under changed from {threshold:g} to "
                    f"{'(removed)' if now is None else f'{now:g}'}",
                    old_range=(min(view.removed), max(view.removed)),
                    new_range=(min(view.added), max(view.added)) if view.added else None,
                    old=f"fail_under {threshold:g}", new=None if now is None else f"fail_under {now:g}",
                    confidence=0.95,
                ))
        lines = view.head_lines()
        reported_keys: set[str] = set()
        disabled = False
        for n, t in sorted(_code_added(view).items()):
            section, key = enclosing_key(lines, n)
            is_cov = (
                "coverage" in section or section in ("run", "report")
                or view.path.endswith(".coveragerc")
            )
            own = _KEY.match(t)
            effective = own.group(1) if own else key
            if is_cov and effective in _COV_SECTION_KEYS and not view.path.endswith(".py"):
                if effective in reported_keys:
                    continue
                reported_keys.add(effective)
                out.append(ctx.finding(
                    self, "omit_added", view.path,
                    f"`{t.strip()}` was added under coverage `{effective}`",
                    new_range=(n, n), new=t, confidence=0.75,
                ))
            elif re.search(r"--no-cov\b|--cov-report=\s*$", t) and not disabled:
                disabled = True
                out.append(ctx.finding(
                    self, "coverage_disabled", view.path, "coverage collection disabled",
                    new_range=(n, n), new=t, confidence=0.85,
                ))
        head_text = view.head_text or ""
        for n, t in sorted(view.removed.items()):
            if (re.search(r"--cov(?![-\w])", t) and not re.search(r"--cov(?![-\w])", head_text)
                    and not disabled):
                out.append(ctx.finding(
                    self, "coverage_disabled", view.path, "`--cov` was removed from the test run",
                    old_range=(n, n), old=t, confidence=0.7,
                ))
                break
        return out


class CiWeakeningRule(BaseRule):
    id = "T010"
    family = Family.CONFIG_WEAKENING
    languages = frozenset({"*"})
    checks = {
        "continue_on_error": CheckSpec(Severity.HIGH, "`continue-on-error: true` added"),
        "step_disabled": CheckSpec(Severity.HIGH, "`if: false` added to a step/job"),
        "or_true": CheckSpec(Severity.HIGH, "`|| true` added to a test/lint command"),
        "test_step_removed": CheckSpec(Severity.HIGH, "a test/lint command was removed from CI or Make"),
        "timeout_increased": CheckSpec(Severity.MEDIUM, "CI timeout increased"),
        "pytest_flag_removed": CheckSpec(Severity.MEDIUM, "strictness flag removed from test config"),
        "tests_deselected": CheckSpec(Severity.HIGH, "--deselect/--ignore/-k \"not\" added"),
        "lint_weakened": CheckSpec(Severity.MEDIUM, "type/lint strictness relaxed in config"),
        "plugin_disabled": CheckSpec(Severity.LOW, "`-p no:<plugin>` added to pytest options"),
        "fail_fast_added": CheckSpec(Severity.INFO, "`-x`/`--maxfail` added (informational)"),
    }
    doc = RuleDoc(
        title="CI / test-config weakening",
        rationale="Checks only protect if they run and can fail: `continue-on-error`, `|| true`, "
        "`if: false`, removed test steps, deselected tests and relaxed strictness all let a "
        "broken PR stay green.",
        example_before="- run: pytest -q",
        example_after="- run: pytest -q || true",
        limitations="Textual and tool-name based. A test step moved to another file in the same "
        "PR is only recognised when the tool still appears in the changed file's head text. "
        "Hand-written wrappers around test commands are not understood.",
        maps_to="T010",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views(Role.CI_WORKFLOW, Role.BUILD_CONFIG, Role.MANIFEST):
            out.extend(self._added(context, view))
            out.extend(self._removed(context, view))
        return out

    def _added(self, ctx: TamperContext, view: FileView) -> list[Finding]:
        out: list[Finding] = []
        base_lines = view.base_lines()
        removed_timeouts = [
            int(m.group(1)) for t in view.removed.values()
            for m in [re.search(r"timeout-minutes:\s*(\d+)", t)] if m
        ]
        ci_like = view.has(Role.CI_WORKFLOW, Role.BUILD_CONFIG)
        for n, t in sorted(_code_added(view).items()):
            def emit(check: str, reason: str, conf: float, n: int = n, t: str = t) -> None:
                out.append(ctx.finding(
                    self, check, view.path, reason, new_range=(n, n), new=t, confidence=conf,
                ))

            if view.has(Role.CI_WORKFLOW):
                if re.search(r"continue-on-error:\s*true\b", t):
                    emit("continue_on_error", "`continue-on-error: true` lets this step fail "
                         "without failing the workflow", 0.9)
                if re.match(r"\s*(-\s*)?if:\s*(false|\$\{\{\s*false\s*\}\})\s*$", t):
                    emit("step_disabled", "`if: false` disables this step/job", 0.95)
                m = re.search(r"timeout-minutes:\s*(\d+)", t)
                if m and removed_timeouts and int(m.group(1)) > max(removed_timeouts):
                    emit("timeout_increased",
                         f"timeout increased from {max(removed_timeouts)} to {m.group(1)} minutes", 0.5)
            if ci_like and _TEST_TOOLS.search(t) and _OR_TRUE.search(t):
                emit("or_true", "test/lint command can no longer fail the job (`|| true`)", 0.9)
            if ci_like and _DESELECT.search(t):
                emit("tests_deselected", "tests are deselected or ignored by the runner options", 0.7)
            if ci_like and _LINT_OFF.search(t):
                emit("lint_weakened", "type/lint strictness relaxed", 0.6)
            if ci_like and re.search(r"(?<![\w-])-p\s+no:\w+", t):
                emit("plugin_disabled", "a pytest plugin is disabled with `-p no:`", 0.4)
            if ci_like and (
                re.search(r"pytest.*(?<![\w-])(-x|--maxfail[= ]\d+)(?![\w-])", t)
                or re.match(r"\s*addopts\s*=.*(?<![\w-])(-x|--maxfail)(?![\w-])", t)
            ):
                emit("fail_fast_added", "runner stops at the first failure (informational)", 0.3)
            section, key = enclosing_key(view.head_lines(), n)
            if (key in ("ignore", "extend-ignore", "per-file-ignores", "extend-per-file-ignores")
                    and ("ruff" in section or view.path.endswith((".flake8", "ruff.toml")))
                    and _norm(t) not in {_norm(x) for x in base_lines}):
                emit("lint_weakened", f"lint rule ignore added under `{key}`", 0.5)
        return out

    def _removed(self, ctx: TamperContext, view: FileView) -> list[Finding]:
        out: list[Finding] = []
        head_text = view.head_text or ""
        if view.has(Role.CI_WORKFLOW, Role.BUILD_CONFIG) and view.base_text:
            gone = sorted(_tools(view.base_text) - _tools(head_text))
            if gone:
                removed_line = next(
                    (n for n, t in sorted(view.removed.items()) if any(g in t for g in gone)),
                    min(view.removed) if view.removed else 1,
                )
                out.append(ctx.finding(
                    self, "test_step_removed", view.path,
                    f"`{', '.join(gone)}` no longer runs in `{view.path}`",
                    old_range=(removed_line, removed_line),
                    old=view.removed.get(removed_line) or gone[0], confidence=0.8,
                ))
        for flag in _STRICT_FLAGS:
            if any(flag in t for t in view.removed.values()) and flag not in head_text:
                n = next(n for n, t in sorted(view.removed.items()) if flag in t)
                out.append(ctx.finding(
                    self, "pytest_flag_removed", view.path,
                    f"strictness flag `{flag.strip()}` was removed",
                    old_range=(n, n), old=view.removed[n], confidence=0.7,
                ))
        base_lines = view.base_lines()
        for n, t in sorted(view.removed.items()):
            section, key = enclosing_key(base_lines, n)
            if key == "filterwarnings" and t.strip().strip("\",'") == "error":
                out.append(ctx.finding(
                    self, "pytest_flag_removed", view.path,
                    "`filterwarnings = error` was removed; warnings no longer fail tests",
                    old_range=(n, n), old=t, confidence=0.7,
                ))
            if re.match(r"\s*xfail_strict\s*=\s*true", t) and not re.search(
                r"xfail_strict\s*=\s*true", head_text
            ):
                out.append(ctx.finding(
                    self, "pytest_flag_removed", view.path,
                    "`xfail_strict = true` was removed; unexpected passes no longer fail",
                    old_range=(n, n), old=t, confidence=0.7,
                ))
        return out


class RetryRule(BaseRule):
    id = "T011"
    family = Family.CONFIG_WEAKENING
    languages = frozenset({"*"})
    checks = {
        "test_sleep": CheckSpec(Severity.LOW, "sleep added to a test"),
        "test_retry_marker": CheckSpec(Severity.MEDIUM, "flaky/retry marker added to a test"),
        "ci_retry": CheckSpec(Severity.MEDIUM, "retries/reruns added to CI or test config"),
    }
    doc = RuleDoc(
        title="Retries and sleeps added to force a pass",
        rationale="Reruns, `@flaky` and sleeps turn a failing signal into a passing one without "
        "fixing the cause; they are common AI shortcuts for flaky or racy tests.",
        example_before="def test_job():\n    start(); assert done()",
        example_after="@pytest.mark.flaky(reruns=5)\ndef test_job():\n    start(); time.sleep(2); assert done()",
        limitations="A `sleep` in a test is weak evidence (confidence 0.4): it is often a "
        "legitimate wait. Retry detection is keyword based.",
        maps_to="T011",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        for view in context.views():
            base = _base_norm(view)
            ci_reported = False
            ci_reported = False
            for n, t in sorted(_code_added(view).items()):
                if _norm(t) in base:
                    continue
                if view.is_test or view.has(Role.CONFTEST):
                    if _RETRY_TEST.search(t):
                        out.append(context.finding(
                            self, "test_retry_marker", view.path,
                            "retry/flaky marker added to a test", new_range=(n, n), new=t,
                            confidence=0.7,
                        ))
                    elif _SLEEP.search(t):
                        out.append(context.finding(
                            self, "test_sleep", view.path, "sleep added to a test",
                            new_range=(n, n), new=t, confidence=0.4,
                        ))
                elif view.has(Role.CI_WORKFLOW, Role.BUILD_CONFIG, Role.MANIFEST) \
                        and _RETRY_CI.search(t) and not ci_reported:
                    ci_reported = True
                    out.append(context.finding(
                        self, "ci_retry", view.path, "retries/reruns added to CI or test config",
                        new_range=(n, n), new=t, confidence=0.6,
                    ))
        return out
