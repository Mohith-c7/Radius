"""SQLAlchemy coverage store adapter.

Same contract and result shapes as :class:`InMemoryCoverageStore`. Each ingestion replaces
the analysis' coverage. Every ``test_id`` in the payload must be a test case of the
analysed repository (or be resolvable by ``test_path`` within it); anything else is a
validation error, so a caller can never attach coverage to another tenant's test cases.

Storage note: file entries and symbol entries share ``coverage_artifacts``. A row with a
symbol is a symbol artifact; a row without one is a file artifact.
"""

from collections.abc import Iterable
from uuid import UUID

from radius_shared.database import coverage as db_models
from radius_shared.database import models as db_schema
from radius_shared.errors import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from radius_confidence.interfaces.store import CoverageStore


class SqlAlchemyCoverageStore(CoverageStore):
    """Persist coverage artifacts, reports and associations in SQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest_coverage(
        self,
        analysis_id: UUID,
        framework: str,
        coverage_percent: float | None,
        files: Iterable[dict],
        symbols: Iterable[dict],
    ) -> None:
        analysis = self._session.get(db_schema.Analysis, analysis_id)
        if analysis is None:
            msg = f"Analysis {analysis_id} was not found."
            raise ValidationError(msg)
        file_items = [_file_item(item) for item in files]
        symbol_items = [_symbol_item(item) for item in symbols]

        report = self._find_or_create_report(analysis_id)
        report.framework = (framework or "unknown")[:100]
        report.coverage_percent = coverage_percent
        self._clear(report)

        associations = self._associations_for(
            report, analysis.repository_id, file_items + symbol_items
        )
        merged: dict[tuple[UUID, str, str | None], db_models.CoverageArtifact] = {}
        for item in file_items + symbol_items:
            assoc = associations[item["key"]]
            key = (assoc.id, item["path"], item["symbol"])
            row = merged.get(key)
            if row is None:
                merged[key] = db_models.CoverageArtifact(
                    report_id=report.id,
                    test_id=assoc.id,
                    path=item["path"],
                    symbol=item["symbol"],
                    count=item["count"],
                    covered=item["covered"],
                )
            else:  # the same test reported the same artifact twice: merge, never duplicate
                row.count += item["count"]
                row.covered = row.covered or item["covered"]
        self._session.add_all(merged.values())
        self._session.flush()

        rows = list(merged.values())
        report.artifact_count = len(rows)
        report.total_lines = len(rows)
        report.covered_lines = sum(1 for row in rows if row.covered)
        self._session.flush()

    def get_coverage_for_artifact(self, analysis_id: UUID, path: str) -> dict | None:
        report = self._load(analysis_id)
        if report is None:
            return None
        artifacts = [
            self._file_to_dict(artifact)
            for artifact in self._artifacts(report)
            if artifact.symbol is None and artifact.path == path
        ]
        return {"report": self._report_to_dict(report), "artifacts": artifacts or None}

    def get_tests_for_symbol(
        self, analysis_id: UUID, file_path: str, symbol: str
    ) -> dict | None:
        report = self._load(analysis_id)
        if report is None:
            return None
        tests = sorted(
            {
                self._association(report, artifact).test_id
                for artifact in self._artifacts(report)
                if artifact.symbol == symbol and artifact.path == file_path
            },
            key=str,
        )
        if not tests:
            return None
        return {"report": self._report_to_dict(report), "tests": tests}

    def get_summary(self, analysis_id: UUID) -> dict | None:
        report = self._session.scalar(
            select(db_models.CoverageReport).where(
                db_models.CoverageReport.analysis_id == analysis_id
            )
        )
        if report is None:
            return None
        return self._summary_to_dict(report)

    def get_report(self, analysis_id: UUID) -> dict | None:
        report = self._load(analysis_id)
        if report is None:
            return None
        artifacts = self._artifacts(report)
        return {
            "report": self._report_to_dict(report),
            "files": [self._file_to_dict(a) for a in artifacts if a.symbol is None],
            "artifacts": [self._symbol_to_dict(a) for a in artifacts if a.symbol is not None],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _find_or_create_report(self, analysis_id: UUID) -> db_models.CoverageReport:
        row = self._session.scalar(
            select(db_models.CoverageReport).where(
                db_models.CoverageReport.analysis_id == analysis_id
            )
        )
        if row is None:
            row = db_models.CoverageReport(analysis_id=analysis_id)
            self._session.add(row)
            self._session.flush()  # assigns report.id for the child rows
        return row

    def _clear(self, report: db_models.CoverageReport) -> None:
        """Replace semantics: drop the previous ingestion's rows of this report."""

        self._session.execute(
            delete(db_models.CoverageArtifact).where(
                db_models.CoverageArtifact.report_id == report.id
            )
        )
        self._session.execute(
            delete(db_models.CoverageReportTestAssociation).where(
                db_models.CoverageReportTestAssociation.report_id == report.id
            )
        )
        self._session.flush()
        self._session.expire(report, ["associations", "artifacts"])

    def _associations_for(
        self,
        report: db_models.CoverageReport,
        repository_id: UUID,
        items: list[dict],
    ) -> dict[tuple[str | None, str | None], db_models.CoverageReportTestAssociation]:
        """One association per referenced test case, validated against the repository."""

        cases = self._session.scalars(
            select(db_schema.TestCase).where(db_schema.TestCase.repository_id == repository_id)
        ).all()
        by_id = {str(case.id): case for case in cases}
        by_path = {_norm(case.path): case for case in cases}
        resolved: dict[tuple[str | None, str | None], db_models.CoverageReportTestAssociation] = {}
        per_case: dict[UUID, db_models.CoverageReportTestAssociation] = {}
        for item in items:
            key = item["key"]
            if key in resolved:
                continue
            test_id, test_path = key
            case = by_id.get(test_id) if test_id else None
            if case is None and test_path:
                case = by_path.get(_norm(test_path))
            if case is None:
                msg = (
                    "Coverage references a test that is not a test case of the analysed "
                    f"repository (test_id={test_id!r}, test_path={test_path!r})."
                )
                raise ValidationError(msg)
            assoc = per_case.get(case.id)
            if assoc is None:
                assoc = db_models.CoverageReportTestAssociation(
                    report_id=report.id, test_id=case.id
                )
                self._session.add(assoc)
                per_case[case.id] = assoc
            resolved[key] = assoc
        self._session.flush()  # assigns association ids for the artifact rows
        return resolved

    def _load(self, analysis_id: UUID) -> db_models.CoverageReport | None:
        return self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
            .options(
                selectinload(db_models.CoverageReport.associations).selectinload(
                    db_models.CoverageReportTestAssociation.test_case
                ),
                selectinload(db_models.CoverageReport.artifacts),
            )
        )

    @staticmethod
    def _artifacts(report: db_models.CoverageReport) -> list[db_models.CoverageArtifact]:
        return sorted(
            report.artifacts, key=lambda a: (a.path, a.symbol or "", str(a.test_id))
        )

    @staticmethod
    def _association(
        report: db_models.CoverageReport, artifact: db_models.CoverageArtifact
    ) -> db_models.CoverageReportTestAssociation:
        return next(a for a in report.associations if a.id == artifact.test_id)

    def _file_to_dict(self, artifact: db_models.CoverageArtifact) -> dict:
        assoc = self._association(artifact.report, artifact)
        return {
            "test_id": assoc.test_id,
            "test_path": assoc.test_case.path if assoc.test_case is not None else "",
            "file_path": artifact.path,
            "symbol": artifact.symbol,
            "executed": artifact.covered,
            "count": artifact.count,
            "covered": artifact.covered,
        }

    def _symbol_to_dict(self, artifact: db_models.CoverageArtifact) -> dict:
        assoc = self._association(artifact.report, artifact)
        return {
            "test_id": assoc.test_id,
            "file_path": artifact.path,
            "symbol": artifact.symbol,
            "executed": artifact.covered,
            "count": artifact.count,
        }

    @staticmethod
    def _report_to_dict(report: db_models.CoverageReport) -> dict:
        return {
            "analysis_id": report.analysis_id,
            "framework": report.framework,
            "coverage_percent": _percent(report.coverage_percent),
            "covered_lines": report.covered_lines,
            "total_lines": report.total_lines,
            "artifact_count": report.artifact_count,
            "created_at": report.created_at,
            "updated_at": report.updated_at,
        }

    @staticmethod
    def _summary_to_dict(report: db_models.CoverageReport) -> dict:
        percent = _percent(report.coverage_percent)
        return {
            "covered_lines": report.covered_lines,
            "total_lines": report.total_lines,
            "coverage_percent": percent,
            "artifact_count": report.artifact_count,
            "available": report.total_lines > 0 and percent is not None,
        }


def _norm(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _percent(value) -> float | None:
    return None if value is None else float(value)


def _key(item: dict) -> tuple[str | None, str | None]:
    test_id = item.get("test_id")
    test_path = item.get("test_path")
    return (str(test_id) if test_id else None, str(test_path) if test_path else None)


def _file_item(item: dict) -> dict:
    if not item.get("path"):
        raise ValidationError("Every coverage file entry needs a 'path'.")
    return {
        "key": _key(item),
        "path": str(item["path"]),
        "symbol": None,
        "count": int(item.get("count", 0) or 0),
        "covered": bool(item.get("covered", False)),
    }


def _symbol_item(item: dict) -> dict:
    if not item.get("file_path") or not item.get("symbol"):
        raise ValidationError("Every coverage symbol entry needs 'file_path' and 'symbol'.")
    return {
        "key": _key(item),
        "path": str(item["file_path"]),
        "symbol": str(item["symbol"]),
        "count": int(item.get("count", 0) or 0),
        "covered": bool(item.get("executed", False)),
    }
