"""In-memory coverage store for local orchestration and tests."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from radius_confidence.domain.coverage import (
    CoverageFile,
    CoverageReportValueObject,
    CoverageSymbol,
)
from radius_confidence.interfaces.store import CoverageStore


class InMemoryCoverageStore(CoverageStore):
    """In-memory coverage store for local orchestration and tests."""

    def __init__(self) -> None:
        self._reports: dict[str, dict] = {}
        self._files: dict[str, dict] = {}
        self._symbols: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # CoverageStore
    # ------------------------------------------------------------------
    def ingest_coverage(
        self,
        analysis_id: UUID,
        framework: str,
        coverage_percent: float | None,
        files: Iterable[dict],
        symbols: Iterable[dict],
    ) -> None:
        key = str(analysis_id)
        self._reports[key] = {
            "analysis_id": analysis_id,
            "framework": framework,
            "coverage_percent": coverage_percent,
            "covered_lines": 0,
            "total_lines": 0,
            "artifact_count": 0,
        }
        self._files[key] = []
        self._symbols[key] = []
        for item in files:
            path = item["path"]
            self._files[key].append(
                {
                    "test_id": item["test_id"],
                    "test_path": item.get("test_path", ""),
                    "file_path": path,
                    "symbol": item.get("symbol") or None,
                    "executed": bool(item.get("covered", False)),
                    "count": int(item.get("count", 0) or 0),
                    "covered": bool(item.get("covered", False)),
                }
            )
        for item in symbols:
            self._symbols[key].append(
                {
                    "test_id": item["test_id"],
                    "file_path": item["file_path"],
                    "symbol": item["symbol"],
                    "executed": bool(item.get("executed", False)),
                    "count": int(item.get("count", 0) or 0),
                }
            )
        all_artifacts = self._files[key] + self._symbols[key]
        self._reports[key]["artifact_count"] = len(all_artifacts)
        self._reports[key]["covered_lines"] = sum(
            1 for item in all_artifacts if item.get("covered", item.get("executed", False))
        )
        self._reports[key]["total_lines"] = len(all_artifacts)

    def get_coverage_for_artifact(self, analysis_id: UUID, path: str) -> dict | None:
        key = str(analysis_id)
        artifacts = [
            item
            for item in self._files.get(key, [])
            if item["file_path"] == path
        ]
        return {"report": self._reports.get(key), "artifacts": artifacts or None}

    def get_tests_for_symbol(
        self, analysis_id: UUID, file_path: str, symbol: str
    ) -> dict | None:
        key = str(analysis_id)
        matching = [
            item
            for item in self._symbols.get(key, [])
            if item["file_path"] == file_path and item["symbol"] == symbol
        ]
        if not matching:
            return None
        tests = sorted(
            {item["test_id"] for item in matching},
            key=lambda t: str(t),
        )
        return {"report": self._reports.get(key), "tests": tests or None}

    def get_summary(self, analysis_id: UUID) -> dict | None:
        key = str(analysis_id)
        report = self._reports.get(key)
        # Legacy callers did not retain the analysis id. Returning the sole
        # report preserves that compatibility without guessing between runs.
        if report is None and len(self._reports) == 1:
            report = next(iter(self._reports.values()))
        if report is None:
            return None
        return {
            "covered_lines": report["covered_lines"],
            "total_lines": report["total_lines"],
            "coverage_percent": report["coverage_percent"],
            "artifact_count": report["artifact_count"],
            "available": bool(
                report["total_lines"] > 0 and report["coverage_percent"] is not None
            ),
        }

    def get_report(self, analysis_id: UUID) -> dict | None:
        key = str(analysis_id)
        return {"report": self._reports.get(key), "files": self._files.get(key, []), "artifacts": self._symbols.get(key, [])}
