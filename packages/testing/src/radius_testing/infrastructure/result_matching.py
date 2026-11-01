"""Attribute uploaded test results to the tests Radius selected.

A CI report is only evidence for a selected test file if the report shows
that file was actually executed. Reports that cannot be attributed (no
``file``/``classname`` information) prove nothing about the selection and are
treated as missing evidence, never as a pass.

Cases from several uploads (CI shards, retries) are merged by identity. A
failure is sticky: a case reported as failed in any upload stays failed even if
another upload reports it as passed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from radius_testing.domain.entities import CaseOutcome, ReportedTestCase

try:
    import defusedxml.ElementTree as _safe_et
except ImportError:  # pragma: no cover - defusedxml is a declared dependency
    _safe_et = None

# Backwards-compatible name: one reported case with location hints.
ExecutedCase = ReportedTestCase

_FAILED_JSON_STATUSES = frozenset({"failed", "failure", "error", "errored", "broken"})
_PASSED_JSON_STATUSES = frozenset({"passed", "pass", "ok", "success", "succeeded"})
_OUTCOME_RANK = {CaseOutcome.SKIPPED: 0, CaseOutcome.PASSED: 1, CaseOutcome.FAILED: 2}


@dataclass(frozen=True, slots=True)
class SelectedTestAttribution:
    """How each selected test file is represented in the uploaded results.

    ``executed`` = ``passed`` + ``failed``. ``skipped`` files only had skipped
    cases and ``not_reported`` files had no case at all; neither counts as
    executed, so both are in ``missing``.
    """

    selected: tuple[str, ...]
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]
    not_reported: tuple[str, ...]

    @property
    def executed(self) -> tuple[str, ...]:
        """Return selected files with at least one executed case."""

        return tuple(path for path in self.selected if path in {*self.passed, *self.failed})

    @property
    def missing(self) -> tuple[str, ...]:
        """Return selected files the results do not show as executed."""

        return tuple(path for path in self.selected if path in {*self.skipped, *self.not_reported})


def report_cases(content: str | bytes) -> tuple[ReportedTestCase, ...]:
    """Extract every reported test case (including skipped) with its outcome.

    JSON reports may provide ``testcases: [{"file", "classname", "name",
    "status"}]`` (top level or per suite). Aggregate-only JSON yields no cases.
    """

    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    stripped = text.strip()
    if not stripped:
        return ()
    if stripped.startswith(("{", "[")):
        return _json_cases(stripped)
    return _xml_cases(stripped)


def executed_cases(content: str | bytes) -> tuple[ReportedTestCase, ...]:
    """Return reported cases that actually ran (skipped cases excluded)."""

    return tuple(case for case in report_cases(content) if case.executed)


def merge_cases(cases: Iterable[ReportedTestCase]) -> tuple[ReportedTestCase, ...]:
    """Merge the same case across uploads; failed beats passed beats skipped."""

    merged: dict[tuple[str, str, str], ReportedTestCase] = {}
    for case in cases:
        current = merged.get(case.key)
        if current is None or _OUTCOME_RANK[case.outcome] > _OUTCOME_RANK[current.outcome]:
            merged[case.key] = case
    return tuple(merged.values())


def attribute_selected_tests(
    selected_test_paths: tuple[str, ...],
    cases: Iterable[ReportedTestCase],
) -> SelectedTestAttribution:
    """Classify each selected test file as passed/failed/skipped/not reported."""

    merged = merge_cases(cases)
    normalized = {path: _norm(path) for path in selected_test_paths}
    # A case whose reported location is only a suffix of a selected path (e.g.
    # runner-relative "test_api.py") is ambiguous when that suffix fits more
    # than one selected file; it then proves nothing about either of them.
    ambiguous = {
        case.key
        for case in merged
        if sum(1 for path in normalized.values() if _case_matches(path, case)) > 1
        and not any(_case_matches(path, case, allow_short=False) for path in normalized.values())
    }
    merged = tuple(case for case in merged if case.key not in ambiguous)
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    not_reported: list[str] = []
    for path in selected_test_paths:
        matches = [case for case in merged if _case_matches(_norm(path), case)]
        outcomes = {case.outcome for case in matches}
        if CaseOutcome.FAILED in outcomes:
            failed.append(path)
        elif CaseOutcome.PASSED in outcomes:
            passed.append(path)
        elif outcomes:
            skipped.append(path)
        else:
            not_reported.append(path)
    return SelectedTestAttribution(
        selected=tuple(selected_test_paths),
        passed=tuple(passed),
        failed=tuple(failed),
        skipped=tuple(skipped),
        not_reported=tuple(not_reported),
    )


def unmatched_selected_tests(
    selected_test_paths: tuple[str, ...],
    cases: tuple[ReportedTestCase, ...],
) -> tuple[str, ...]:
    """Return selected test files with no executed case in the report."""

    executed = [case for case in cases if case.executed]
    return tuple(
        path
        for path in selected_test_paths
        if not any(_case_matches(_norm(path), case) for case in executed)
    )


def _case_matches(path: str, case: ReportedTestCase, *, allow_short: bool = True) -> bool:
    if case.file:
        reported = _norm(case.file)
        # Reports may use absolute paths (reported ends with the selected
        # path) or runner-relative ones (selected path ends with reported).
        if reported == path or reported.endswith("/" + path):
            return True
        # A bare file name ("test_api.py") could be any same-named test file,
        # so the runner-relative form needs at least one directory component.
        if allow_short and "/" in reported and path.endswith("/" + reported):
            return True
    if case.classname:
        classname = case.classname.strip()
        normalized = _norm(classname)
        if normalized == path or normalized.endswith("/" + path):
            return True  # vitest/jest-junit style: classname is the file path
        module = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
        if classname == module or classname.startswith(module + "."):
            return True  # pytest style: dotted module (optionally + class)
    return False


def _norm(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _xml_cases(text: str) -> tuple[ReportedTestCase, ...]:
    if _safe_et is None:  # pragma: no cover
        return ()
    try:
        root = _safe_et.fromstring(text.encode("utf-8"))
    except Exception:  # noqa: BLE001 - malformed reports yield no evidence
        return ()
    cases: list[ReportedTestCase] = []
    for testcase in root.iter("testcase"):
        if testcase.findall("failure") or testcase.findall("error"):
            outcome = CaseOutcome.FAILED
        elif testcase.findall("skipped"):
            outcome = CaseOutcome.SKIPPED  # a skipped case is not evidence the file ran
        else:
            outcome = CaseOutcome.PASSED
        cases.append(
            ReportedTestCase(
                file=testcase.get("file"),
                classname=testcase.get("classname"),
                name=testcase.get("name"),
                outcome=outcome,
            )
        )
    return tuple(cases)


def _json_cases(text: str) -> tuple[ReportedTestCase, ...]:
    try:
        data = json.loads(text)
    except ValueError:
        return ()
    containers = data if isinstance(data, list) else [data]
    cases: list[ReportedTestCase] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        for item in container.get("testcases", ()) or ():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status in _FAILED_JSON_STATUSES:
                outcome = CaseOutcome.FAILED
            elif status in _PASSED_JSON_STATUSES:
                outcome = CaseOutcome.PASSED
            else:
                # Skipped, timed out, cancelled, missing or unknown statuses are
                # not evidence that the case ran and passed.
                outcome = CaseOutcome.SKIPPED
            cases.append(
                ReportedTestCase(
                    file=_optional_str(item.get("file")),
                    classname=_optional_str(item.get("classname")),
                    name=_optional_str(item.get("name")),
                    outcome=outcome,
                )
            )
    return tuple(cases)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
