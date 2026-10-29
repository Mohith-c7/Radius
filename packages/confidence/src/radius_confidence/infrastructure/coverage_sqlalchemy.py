"""SQLAlchemy coverage store adapter."""

from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from radius_shared.database import coverage as db_models
from radius_shared.database import models as db_schema
from radius_shared.errors import ValidationError
from sqlalchemy.orm import Session

from radius_confidence.domain.coverage import (
    CoverageFile,
    CoverageReportValueObject,
    CoverageSymbol,
)
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
        self._require_analysis(analysis_id)
        report = self._find_or_create_report(analysis_id)
        association_ids = self._persist_associations(report, framework)
        self._persist_artifacts(report, association_ids, files)
        self._persist_symbols(report, association_ids, symbols)
        self._update_report_summary(report, len(association_ids))

    def get_coverage_for_artifact(self, analysis_id: UUID, path: str) -> dict | None:
        report = self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
            .options(selectinload(db_models.CoverageReport.artifacts))
        )
        if report is None:
            return None
        artifacts = [
            self._artifact_to_dict(a)
            for a in report.artifacts
            if a.path == path
        ]
        return {"report": self._report_to_dict(report), "artifacts": artifacts or None}

    def get_tests_for_symbol(
        self, analysis_id: UUID, file_path: str, symbol: str
    ) -> dict | None:
        report = self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
            .options(
                selectinload(db_models.CoverageReport.associations).selectinload(
                    db_models.CoverageReportTestAssociation.test_case
                ),
                selectinload(db_models.CoverageReport.artifacts),
            )
        )
        if report is None:
            return None
        matching = [
            a
            for a in report.artifacts
            if a.file_path == file_path and a.symbol == symbol
        ]
        if not matching:
            return None
        def _test_by_id(test_id: UUID):
            for assoc in report.associations:
                if assoc.id == test_id:
                    return assoc.test_case
            return None

        tests = sorted(
            {test for a in matching for test in [_test_by_id(a.test_id)] if test is not None},
            key=lambda t: t.path if hasattr(t, "path") else "",
        )
        return {"report": self._report_to_dict(report), "tests": tests or None}

    def get_summary(self, analysis_id: UUID) -> dict | None:
        row = self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
        )
        if row is None:
            return None
        return self._summary_to_dict(row)

    def get_report(self, analysis_id: UUID) -> dict | None:
        row = self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
            .options(
                selectinload(db_models.CoverageReport.associations).selectinload(
                    db_models.CoverageReportTestAssociation.test_case
                ),
                selectinload(db_models.CoverageReport.artifacts),
            )
        )
        if row is None:
            return None
        return {"report": self._report_to_dict(row), "files": [], "artifacts": []}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_analysis(self, analysis_id: UUID) -> None:
        if self._session.get(db_schema.Analysis, analysis_id) is None:
            msg = f"Analysis {analysis_id} was not found."
            raise ValidationError(msg)

    def _find_or_create_report(self, analysis_id: UUID) -> db_models.CoverageReport:
        row = self._session.scalar(
            select(db_models.CoverageReport)
            .where(db_models.CoverageReport.analysis_id == analysis_id)
        )
        if row is None:
            row = db_models.CoverageReport(analysis_id=analysis_id)
            self._session.add(row)
        return row

    def _persist_associations(
        self, report: db_models.CoverageReport, framework: str
    ) -> list[UUID]:
        ids: list[UUID] = []
        for assoc in report.associations:
            self._session.delete(assoc)
        self._session.flush()
        return ids

    def _persist_artifacts(
        self,
        report: db_models.CoverageReport,
        association_ids: list[UUID],
        files: Iterable[dict],
    ) -> None:
        rows = [
            db_models.CoverageArtifact(
                test_id=assoc_id,
                path=str(item["path"]),
                symbol=item.get("symbol") or None,
                count=int(item.get("count", 0) or 0),
                covered=bool(item.get("covered", False)),
            )
            for item in files
            for assoc_id in association_ids
        ]
        self._session.add_all(rows)
        self._session.flush()
        report.artifact_count = len(rows)

    def _persist_symbols(
        self,
        report: db_models.CoverageReport,
        association_ids: list[UUID],
        symbols: Iterable[dict],
    ) -> None:
        for item in symbols:
            for assoc_id in association_ids:
                self._session.add(
                    db_models.CoverageArtifact(
                        test_id=assoc_id,
                        path=str(item.get("file_path", "")),
                        symbol=str(item.get("symbol", "") or None),
                        count=int(item.get("count", 0) or 0),
                        covered=bool(item.get("executed", False)),
                    )
                )
        self._session.flush()
        report.artifact_count = (
            self._session.scalar(
                select(db_models.CoverageArtifact)
                .where(db_models.CoverageArtifact.report_id == report.id)
            ).id
            or 0
        )

    def _update_report_summary(self, report: db_models.CoverageReport, test_count: int) -> None:
        artifacts = self._session.scalars(
            select(db_models.CoverageArtifact).where(
                db_models.CoverageArtifact.report_id == report.id
            )
        ).all()
        covered = sum(1 for a in artifacts if a.covered)
        total = len(artifacts)
        report.covered_lines = covered
        report.total_lines = total
        report.artifact_count = len(artifacts)
        if total:
            report.coverage_percent = round(covered * 100 / total, 2)

    def _artifact_to_dict(self, artifact: db_models.CoverageArtifact) -> dict:
        return {
            "test_id": artifact.test_id,
            "test_path": None,
            "file_path": artifact.path,
            "symbol": artifact.symbol,
            "executed": artifact.covered,
            "count": artifact.count,
            "covered": artifact.covered,
        }

    def _report_to_dict(self, report: db_models.CoverageReport) -> dict:
        return {
            "analysis_id": report.analysis_id,
            "framework": report.framework,
            "covered_lines": report.covered_lines,
            "total_lines": report.total_lines,
            "coverage_percent": report.coverage_percent,
            "artifact_count": report.artifact_count,
            "created_at": report.created_at,
            "updated_at": report.updated_at,
        }

    def _summary_to_dict(self, report: db_models.CoverageReport) -> dict:
        return {
            "covered_lines": report.covered_lines,
            "total_lines": report.total_lines,
            "coverage_percent": report.coverage_percent,
            "artifact_count": report.artifact_count,
            "available": report.total_lines > 0 and report.coverage_percent is not None,
        }
