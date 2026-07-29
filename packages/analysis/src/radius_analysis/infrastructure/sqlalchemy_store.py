"""SQLAlchemy analysis store adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.errors import NotFoundError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from radius_analysis.domain.entities import Analysis, BlastRadius, ChangedFile
from radius_analysis.domain.enums import AnalysisStatus, ChangedFileType
from radius_analysis.domain.value_objects import CommitSha, FilePath


class SqlAlchemyAnalysisStore:
    """Analysis persistence backed by Radius SQLAlchemy models."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Return one analysis by id."""

        row = self._session.scalar(
            self._analysis_query().where(db_models.Analysis.id == analysis_id)
        )
        return self._to_domain(row)

    def list(
        self,
        repository_id: UUID | None = None,
        pull_request_id: UUID | None = None,
        status: AnalysisStatus | None = None,
    ) -> list[Analysis]:
        """Return analyses matching optional filters."""

        statement = self._analysis_query()
        if repository_id is not None:
            statement = statement.where(
                db_models.Analysis.repository_id == repository_id
            )
        if pull_request_id is not None:
            statement = statement.where(
                db_models.Analysis.pull_request_id == pull_request_id
            )
        if status is not None:
            statement = statement.where(
                db_models.Analysis.status == db_enums.AnalysisStatus(status.value)
            )

        rows = self._session.scalars(
            statement.order_by(db_models.Analysis.created_at.desc())
        ).all()
        return [self._to_domain(row) for row in rows if row is not None]

    def save(self, analysis: Analysis) -> Analysis:
        """Persist an analysis."""

        if analysis.id is not None:
            row = self._session.get(db_models.Analysis, analysis.id)
            if row is None:
                msg = f"Analysis {analysis.id} was not found."
                raise NotFoundError(msg)
        else:
            row = db_models.Analysis()
            self._session.add(row)

        row.repository_id = analysis.repository_id
        row.pull_request_id = analysis.pull_request_id
        row.commit_sha = analysis.commit_sha.value
        row.status = db_enums.AnalysisStatus(analysis.status.value)
        row.started_at = analysis.started_at
        row.completed_at = analysis.completed_at
        row.created_at = analysis.created_at

        self._session.flush()
        self._session.refresh(row, attribute_names=["changed_files", "blast_radius"])
        domain = self._to_domain(row)
        if domain is None:
            msg = "Analysis could not be saved."
            raise NotFoundError(msg)
        return domain

    def update_status(
        self,
        analysis_id: UUID,
        status: AnalysisStatus,
    ) -> Analysis:
        """Update analysis status and terminal timestamp."""

        row = self._session.get(db_models.Analysis, analysis_id)
        if row is None:
            msg = f"Analysis {analysis_id} was not found."
            raise NotFoundError(msg)

        row.status = db_enums.AnalysisStatus(status.value)
        if status in {
            AnalysisStatus.COMPLETED,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        }:
            row.completed_at = datetime.now(UTC)
        self._session.flush()
        self._session.refresh(row, attribute_names=["changed_files", "blast_radius"])
        domain = self._to_domain(row)
        if domain is None:
            msg = f"Analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return domain

    def replace_changed_files(
        self,
        analysis_id: UUID,
        changed_files: list[ChangedFile],
    ) -> list[ChangedFile]:
        """Replace changed-file evidence for an analysis."""

        self._require_analysis(analysis_id)
        self._session.execute(
            delete(db_models.ChangedFile).where(
                db_models.ChangedFile.analysis_id == analysis_id
            )
        )
        rows = [
            db_models.ChangedFile(
                analysis_id=analysis_id,
                path=changed_file.path.value,
                change_type=db_enums.ChangedFileType(
                    changed_file.change_type.value
                ),
                additions=changed_file.additions,
                deletions=changed_file.deletions,
            )
            for changed_file in changed_files
        ]
        self._session.add_all(rows)
        self._session.flush()
        for row in rows:
            self._session.refresh(row)
        return [self._changed_file_to_domain(row) for row in rows]

    def save_blast_radius(self, blast_radius: BlastRadius) -> BlastRadius:
        """Create or update blast-radius summary."""

        self._require_analysis(blast_radius.analysis_id)
        row = self._session.scalar(
            select(db_models.BlastRadius).where(
                db_models.BlastRadius.analysis_id == blast_radius.analysis_id
            )
        )
        if row is None:
            row = db_models.BlastRadius(analysis_id=blast_radius.analysis_id)
            self._session.add(row)

        row.affected_files = blast_radius.affected_files
        row.affected_symbols = blast_radius.affected_symbols
        row.affected_modules = blast_radius.affected_modules
        row.affected_tests = blast_radius.affected_tests
        row.dependency_depth = blast_radius.dependency_depth

        self._session.flush()
        self._session.refresh(row)
        return self._blast_radius_to_domain(row)

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        """Return blast-radius summary for one analysis."""

        row = self._session.scalar(
            select(db_models.BlastRadius).where(
                db_models.BlastRadius.analysis_id == analysis_id
            )
        )
        if row is None:
            return None
        return self._blast_radius_to_domain(row)

    @staticmethod
    def _analysis_query():
        return select(db_models.Analysis).options(
            selectinload(db_models.Analysis.changed_files),
            selectinload(db_models.Analysis.blast_radius),
        )

    def _require_analysis(self, analysis_id: UUID) -> None:
        if self._session.get(db_models.Analysis, analysis_id) is None:
            msg = f"Analysis {analysis_id} was not found."
            raise NotFoundError(msg)

    @classmethod
    def _to_domain(cls, row: db_models.Analysis | None) -> Analysis | None:
        if row is None:
            return None

        return Analysis(
            id=row.id,
            repository_id=row.repository_id,
            pull_request_id=row.pull_request_id,
            commit_sha=CommitSha(row.commit_sha),
            status=AnalysisStatus(row.status.value),
            started_at=row.started_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
            changed_files=[
                cls._changed_file_to_domain(changed_file)
                for changed_file in row.changed_files
            ],
            blast_radius=(
                cls._blast_radius_to_domain(row.blast_radius)
                if row.blast_radius is not None
                else None
            ),
        )

    @staticmethod
    def _changed_file_to_domain(row: db_models.ChangedFile) -> ChangedFile:
        return ChangedFile(
            id=row.id,
            analysis_id=row.analysis_id,
            path=FilePath(row.path),
            change_type=ChangedFileType(row.change_type.value),
            additions=row.additions,
            deletions=row.deletions,
        )

    @staticmethod
    def _blast_radius_to_domain(row: db_models.BlastRadius) -> BlastRadius:
        return BlastRadius(
            id=row.id,
            analysis_id=row.analysis_id,
            affected_files=row.affected_files,
            affected_symbols=row.affected_symbols,
            affected_modules=row.affected_modules,
            affected_tests=row.affected_tests,
            dependency_depth=row.dependency_depth,
        )
