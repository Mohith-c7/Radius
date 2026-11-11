"""SQLAlchemy adapter for normalized, per-test runtime coverage."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from radius_shared.database import coverage as db_models
from radius_shared.database import models as db_schema
from radius_shared.errors import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from radius_confidence.interfaces.store import CoverageStore


class SqlAlchemyCoverageStore(CoverageStore):
    """Persist reports and actual test-to-file/symbol execution links."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest_coverage(self, analysis_id: UUID, framework: str, coverage_percent: float | None, files: Iterable[dict], symbols: Iterable[dict]) -> None:
        analysis = self._session.get(db_schema.Analysis, analysis_id)
        if analysis is None:
            raise ValidationError(f"Analysis {analysis_id} was not found.")
        repository_id = analysis.repository_id
        report = self._report_for(analysis_id)
        report.framework = framework
        report.coverage_percent = coverage_percent
        for association in list(report.associations):
            self._session.delete(association)
        for artifact in list(report.artifacts):
            self._session.delete(artifact)
        self._session.flush()

        associations: dict[UUID, db_models.CoverageReportTestAssociation] = {}
        for item in [*files, *symbols]:
            test_case = self._test_case_for(item, repository_id)
            if test_case is None:
                continue
            association = associations.get(test_case.id)
            if association is None:
                association = db_models.CoverageReportTestAssociation(
                    report_id=report.id, test_id=test_case.id,
                    passed=bool(item.get("passed", True)),
                    failures=int(item.get("failures", 0)), skipped=int(item.get("skipped", 0)),
                )
                self._session.add(association)
                self._session.flush()
                associations[test_case.id] = association
            self._session.add(db_models.CoverageArtifact(
                report_id=report.id, test_id=association.id,
                path=str(item.get("file_path") or item.get("path") or ""),
                symbol=item.get("symbol") or None,
                count=int(item.get("count", 0) or 0),
                covered=bool(item.get("executed", item.get("covered", False))),
            ))
        self._session.flush()
        artifacts = self._session.scalars(select(db_models.CoverageArtifact).where(db_models.CoverageArtifact.report_id == report.id)).all()
        report.artifact_count = len(artifacts)
        report.covered_lines = sum(item.covered for item in artifacts)
        report.total_lines = len(artifacts)
        if coverage_percent is None and artifacts:
            report.coverage_percent = round(report.covered_lines * 100 / report.total_lines, 2)

    def get_coverage_for_artifact(self, analysis_id: UUID, path: str) -> dict | None:
        report = self._loaded_report(analysis_id)
        if report is None:
            return None
        return {"report": self._report_dict(report), "artifacts": [self._artifact_dict(item, report) for item in report.artifacts if item.path == path]}

    def get_tests_for_symbol(self, analysis_id: UUID, file_path: str, symbol: str) -> dict | None:
        report = self._loaded_report(analysis_id)
        if report is None:
            return None
        association_by_id = {item.id: item for item in report.associations}
        tests = []
        for artifact in report.artifacts:
            if artifact.path == file_path and artifact.symbol == symbol:
                association = association_by_id.get(artifact.test_id)
                if association is not None:
                    tests.append(association.test_case)
        return {"report": self._report_dict(report), "tests": list({test.id: test for test in tests}.values())} if tests else None

    def get_summary(self, analysis_id: UUID) -> dict | None:
        report = self._session.scalar(select(db_models.CoverageReport).where(db_models.CoverageReport.analysis_id == analysis_id))
        return self._summary_dict(report) if report else None

    def get_report(self, analysis_id: UUID) -> dict | None:
        report = self._loaded_report(analysis_id)
        if report is None:
            return None
        files: dict[str, list[db_models.CoverageArtifact]] = defaultdict(list)
        for artifact in report.artifacts:
            files[artifact.path].append(artifact)
        return {
            "report": self._report_dict(report),
            "files": [self._file_dict(path, artifacts) for path, artifacts in sorted(files.items())],
            "artifacts": [self._artifact_dict(item, report) for item in report.artifacts],
        }

    def get_selection_evidence(self, analysis_id: UUID, changed_paths: tuple[str, ...], changed_symbols: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
        analysis = self._session.get(db_schema.Analysis, analysis_id)
        if analysis is None or (not changed_paths and not changed_symbols):
            return {}
        reports = self._session.scalars(
            select(db_models.CoverageReport)
            .join(db_schema.Analysis, db_models.CoverageReport.analysis_id == db_schema.Analysis.id)
            .where(db_schema.Analysis.repository_id == analysis.repository_id)
            .options(selectinload(db_models.CoverageReport.associations).selectinload(db_models.CoverageReportTestAssociation.test_case), selectinload(db_models.CoverageReport.artifacts))
        ).all()
        evidence: dict[str, list[str]] = defaultdict(list)
        for report in reports:
            associations = {item.id: item for item in report.associations}
            for artifact in report.artifacts:
                if artifact.path not in changed_paths and artifact.symbol not in changed_symbols:
                    continue
                association = associations.get(artifact.test_id)
                if association is None:
                    continue
                detail = f"Runtime coverage executes {artifact.symbol} in {artifact.path}." if artifact.symbol else f"Runtime coverage covers {artifact.path}."
                evidence[association.test_case.path].append(detail)
        return {path: tuple(dict.fromkeys(details)) for path, details in evidence.items()}

    def _report_for(self, analysis_id: UUID) -> db_models.CoverageReport:
        report = self._loaded_report(analysis_id)
        if report is None:
            report = db_models.CoverageReport(analysis_id=analysis_id, framework="unknown")
            self._session.add(report)
            self._session.flush()
        return report

    def _loaded_report(self, analysis_id: UUID) -> db_models.CoverageReport | None:
        return self._session.scalar(select(db_models.CoverageReport).where(db_models.CoverageReport.analysis_id == analysis_id).options(selectinload(db_models.CoverageReport.associations).selectinload(db_models.CoverageReportTestAssociation.test_case), selectinload(db_models.CoverageReport.artifacts)))

    def _test_case_for(self, item: dict, repository_id: UUID):
        if item.get("test_id"):
            test_case = self._session.get(db_schema.TestCase, item["test_id"])
            if test_case is None or test_case.repository_id != repository_id:
                return None
            return test_case

        if item.get("test_path"):
            return self._session.scalar(
                select(db_schema.TestCase).where(
                    db_schema.TestCase.repository_id == repository_id,
                    db_schema.TestCase.path == item["test_path"],
                )
            )


        return None

    @staticmethod
    def _summary_dict(report: db_models.CoverageReport) -> dict:
        return {"covered_lines": report.covered_lines, "total_lines": report.total_lines, "coverage_percent": float(report.coverage_percent) if report.coverage_percent is not None else None, "artifact_count": report.artifact_count, "available": report.coverage_percent is not None}

    def _report_dict(self, report: db_models.CoverageReport) -> dict:
        return {"analysis_id": report.analysis_id, "framework": report.framework, **self._summary_dict(report), "created_at": report.created_at, "updated_at": report.updated_at}

    @staticmethod
    def _file_dict(path: str, artifacts: list[db_models.CoverageArtifact]) -> dict:
        total = len(artifacts)
        covered = sum(item.covered for item in artifacts)
        return {"file_path": path, "source_language": "unknown", "covered_lines": covered, "total_lines": total, "covered_percent": round(covered * 100 / total, 2) if total else None}

    @staticmethod
    def _artifact_dict(artifact: db_models.CoverageArtifact, report: db_models.CoverageReport) -> dict:
        associations = {item.id: item for item in report.associations}
        association = associations.get(artifact.test_id)
        return {"test_id": association.test_case.id if association else None, "test_path": association.test_case.path if association else "", "file_path": artifact.path, "symbol": artifact.symbol, "executed": artifact.covered, "count": artifact.count, "covered": artifact.covered}
