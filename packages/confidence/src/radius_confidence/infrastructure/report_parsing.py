"""Parsers for CI coverage artifacts without inventing test relationships."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCoverageReport:
    framework: str
    coverage_percent: float | None
    files: tuple[dict, ...]
    symbols: tuple[dict, ...]


def parse_coverage_report(report_format: str, content: str, framework: str = "unknown") -> ParsedCoverageReport:
    """Parse LCOV or coverage.py JSON into Radius' normalized coverage payload."""
    normalized = report_format.lower().replace("_", "-")
    if normalized in {"lcov", "lcov.info"}:
        return _parse_lcov(content, framework)
    if normalized in {"coverage-json", "coverage.py-json", "coveragepy-json"}:
        return _parse_coverage_py_json(content, framework)
    raise ValueError(f"Unsupported coverage report format: {report_format}.")


def _parse_lcov(content: str, framework: str) -> ParsedCoverageReport:
    files: list[dict] = []
    symbols: list[dict] = []
    total = covered = 0
    test_path = source_file = ""
    functions: dict[str, int] = {}

    def flush() -> None:
        nonlocal functions
        if source_file and test_path:
            files.append({"test_path": test_path, "path": source_file, "covered": True, "count": 1})
            for symbol, count in functions.items():
                symbols.append({"test_path": test_path, "file_path": source_file, "symbol": symbol, "executed": count > 0, "count": count})
        functions = {}

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("TN:"):
            test_path = line[3:]
        elif line.startswith("SF:"):
            source_file = line[3:]
        elif line.startswith("FN:"):
            _, name = line[3:].split(",", 1)
            functions.setdefault(name, 0)
        elif line.startswith("FNDA:"):
            count, name = line[5:].split(",", 1)
            functions[name] = int(count)
        elif line.startswith("DA:"):
            _, count = line[3:].split(",", 1)
            total += 1
            covered += int(count) > 0
        elif line == "end_of_record":
            flush()
            source_file = ""
    percent = round(covered * 100 / total, 2) if total else None
    return ParsedCoverageReport(framework, percent, tuple(files), tuple(symbols))


def _parse_coverage_py_json(content: str, framework: str) -> ParsedCoverageReport:
    payload = json.loads(content)
    files: list[dict] = []
    total = covered = 0
    for path, item in payload.get("files", {}).items():
        summary = item.get("summary", {})
        total += int(summary.get("num_statements", 0))
        covered += int(summary.get("covered_lines", 0))
        files.append({"path": path, "covered": bool(summary.get("covered_lines", 0)), "count": int(summary.get("covered_lines", 0))})
    percent = round(covered * 100 / total, 2) if total else None
    return ParsedCoverageReport(framework, percent, tuple(files), ())
