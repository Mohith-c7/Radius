"""Attribute uploaded test results to the tests Radius selected.

A CI report is only evidence for a selected test file if the report shows
that file was actually executed. Reports that cannot be attributed (no
``file``/``classname`` information) prove nothing about the selection and are
treated as missing evidence, never as a pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath

try:
    import defusedxml.ElementTree as _safe_et
except ImportError:  # pragma: no cover - defusedxml is a declared dependency
    _safe_et = None


@dataclass(frozen=True, slots=True)
class ExecutedCase:
    """Location hints for one executed test case from a CI report."""

    file: str | None = None
    classname: str | None = None


def executed_cases(content: str | bytes) -> tuple[ExecutedCase, ...]:
    """Extract per-test-case location hints from JUnit XML or JSON reports.

    JSON reports may provide ``testcases: [{"file": ..., "classname": ...}]``
    (top level or per suite). Aggregate-only JSON yields no cases.
    """

    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    stripped = text.strip()
    if not stripped:
        return ()
    if stripped.startswith(("{", "[")):
        return _json_cases(stripped)
    return _xml_cases(stripped)


def unmatched_selected_tests(
    selected_test_paths: tuple[str, ...],
    cases: tuple[ExecutedCase, ...],
) -> tuple[str, ...]:
    """Return selected test files with no executed case in the report."""

    files = {_norm(case.file) for case in cases if case.file}
    classnames = {case.classname.strip() for case in cases if case.classname}
    missing: list[str] = []
    for path in selected_test_paths:
        if not _matched(_norm(path), files, classnames):
            missing.append(path)
    return tuple(missing)


def _matched(path: str, files: set[str], classnames: set[str]) -> bool:
    for reported in files:
        # Reports may use absolute or runner-relative paths.
        if reported == path or reported.endswith("/" + path) or path.endswith("/" + reported):
            return True
    module = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
    for classname in classnames:
        normalized = _norm(classname)
        if normalized == path or normalized.endswith("/" + path):
            return True  # vitest/jest-junit style: classname is the file path
        if classname == module or classname.startswith(module + "."):
            return True  # pytest style: dotted module (optionally + class)
    return False


def _norm(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _xml_cases(text: str) -> tuple[ExecutedCase, ...]:
    if _safe_et is None:  # pragma: no cover
        return ()
    try:
        root = _safe_et.fromstring(text.encode("utf-8"))
    except Exception:  # noqa: BLE001 - malformed reports yield no evidence
        return ()
    cases: list[ExecutedCase] = []
    for testcase in root.iter("testcase"):
        if testcase.findall("skipped"):
            continue  # a skipped case is not evidence that the file ran
        cases.append(
            ExecutedCase(
                file=testcase.get("file"),
                classname=testcase.get("classname"),
            )
        )
    return tuple(cases)


def _json_cases(text: str) -> tuple[ExecutedCase, ...]:
    try:
        data = json.loads(text)
    except ValueError:
        return ()
    containers = data if isinstance(data, list) else [data]
    cases: list[ExecutedCase] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        for item in container.get("testcases", ()) or ():
            if isinstance(item, dict) and item.get("status") != "skipped":
                cases.append(
                    ExecutedCase(
                        file=item.get("file"),
                        classname=item.get("classname"),
                    )
                )
    return tuple(cases)
