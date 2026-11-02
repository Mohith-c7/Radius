"""SQLAlchemy IntentRepository (PostgreSQL in CI, SQLite in unit tests).

Rows live in ``radius_shared.database.intent``. The repository flushes but never
commits; the caller owns the transaction. Every query filters by
``organization_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from radius_shared.database import models as db_models
from radius_shared.database.intent import (
    IntentCriterionRow,
    IntentCriterionStateChangeRow,
    IntentSnapshotRow,
    IntentSnapshotSourceRow,
    IntentSourceRow,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from radius_intent.domain import (
    Criterion,
    CriterionState,
    ExtractionMethod,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    Provenance,
    SourceRef,
    Span,
    Testability,
)
from radius_intent.infrastructure.rules import (
    apply_state_change,
    as_utc,
    parse_uuid,
    require_aware,
    snapshot_content_hash,
    validate_actor,
    validate_criterion,
    validate_source,
)
from radius_intent.interfaces.repository import (
    AnalysisNotFoundError,
    CriterionNotFoundError,
    CriterionStateChange,
    SnapshotConflictError,
    SnapshotNotFoundError,
    SourceNotFoundError,
)

_SourceKey = tuple[str, str, str]


def _to_source(row: IntentSourceRow) -> IntentSource:
    return IntentSource(
        source_id=row.source_ref,
        kind=IntentSourceKind(row.kind),
        text=row.text,
        raw_text_hash=row.raw_text_hash,
        fetched_at=as_utc(row.fetched_at),
        truncated=row.truncated,
        suspicious_content_removed=row.suspicious_content_removed,
    )


def _to_ref(row: IntentSourceRow) -> SourceRef:
    return SourceRef(IntentSourceKind(row.kind), row.source_ref, row.raw_text_hash)


def _to_criterion(row: IntentCriterionRow) -> Criterion:
    ref = _to_ref(row.source)
    return Criterion(
        id=row.criterion_id,
        text=row.text,
        normalized_text=row.normalized_text,
        origin=Provenance(
            source=ref,
            retrieved_at=as_utc(row.origin_retrieved_at),
            extraction_method=ExtractionMethod(row.extraction_method),
            extractor_version=row.extractor_version,
        ),
        span=Span(row.source.source_ref, row.span_start, row.span_end),
        weight=row.weight,
        testability=Testability(row.testability),
        testability_rationale=row.testability_rationale,
        state=CriterionState(row.state),
    )


def _to_snapshot(row: IntentSnapshotRow) -> IntentSnapshot:
    return IntentSnapshot(
        snapshot_id=str(row.id),
        analysis_id=str(row.analysis_id),
        version=row.version,
        created_at=as_utc(row.created_at),
        criteria=tuple(_to_criterion(c) for c in row.criteria),
        sources=tuple(_to_ref(link.source) for link in row.source_links),
        parent_snapshot_id=(
            str(row.parent_snapshot_id) if row.parent_snapshot_id else None
        ),
    )


def _try_uuid(value: str) -> UUID | None:
    try:
        return parse_uuid(value, "id")
    except ValueError:
        return None


class SqlAlchemyIntentRepository:
    """Persist intent sources, snapshots, criteria and the audit trail."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- helpers -----------------------------------------------------------

    def _require_analysis(self, organization_id: UUID, analysis_id: UUID) -> None:
        found = self._session.scalar(
            select(db_models.Analysis.id)
            .join(
                db_models.Repository,
                db_models.Repository.id == db_models.Analysis.repository_id,
            )
            .where(
                db_models.Analysis.id == analysis_id,
                db_models.Repository.organization_id == organization_id,
            )
        )
        if found is None:
            msg = "Analysis not found."
            raise AnalysisNotFoundError(msg)

    def _source_rows(
        self, organization_id: UUID, analysis_id: UUID
    ) -> dict[_SourceKey, IntentSourceRow]:
        rows = self._session.scalars(
            select(IntentSourceRow).where(
                IntentSourceRow.organization_id == organization_id,
                IntentSourceRow.analysis_id == analysis_id,
            )
        ).all()
        return {(r.kind, r.source_ref, r.raw_text_hash): r for r in rows}

    def _snapshot_query(self, organization_id: UUID):
        return (
            select(IntentSnapshotRow)
            .where(IntentSnapshotRow.organization_id == organization_id)
            .execution_options(populate_existing=True)
            .options(
                selectinload(IntentSnapshotRow.source_links).selectinload(
                    IntentSnapshotSourceRow.source
                ),
                selectinload(IntentSnapshotRow.criteria).selectinload(
                    IntentCriterionRow.source
                ),
            )
        )

    # -- sources -----------------------------------------------------------

    def save_sources(
        self,
        organization_id: UUID,
        analysis_id: str,
        sources: tuple[IntentSource, ...],
    ) -> None:
        analysis_uuid = parse_uuid(analysis_id, "analysis_id")
        for source in sources:
            validate_source(source)
        self._require_analysis(organization_id, analysis_uuid)
        existing = self._source_rows(organization_id, analysis_uuid)
        for source in sources:
            key = (source.kind.value, source.source_id, source.raw_text_hash)
            if key in existing:
                continue
            row = IntentSourceRow(
                organization_id=organization_id,
                analysis_id=analysis_uuid,
                kind=source.kind.value,
                source_ref=source.source_id,
                text=source.text,
                raw_text_hash=source.raw_text_hash,
                truncated=source.truncated,
                suspicious_content_removed=source.suspicious_content_removed,
                fetched_at=as_utc(source.fetched_at),
                created_at=datetime.now(UTC),
            )
            self._session.add(row)
            existing[key] = row
        self._session.flush()

    def get_sources(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSource, ...]:
        analysis_uuid = _try_uuid(analysis_id)
        if analysis_uuid is None:
            return ()
        rows = self._session.scalars(
            select(IntentSourceRow)
            .where(
                IntentSourceRow.organization_id == organization_id,
                IntentSourceRow.analysis_id == analysis_uuid,
            )
            .order_by(
                IntentSourceRow.kind,
                IntentSourceRow.source_ref,
                IntentSourceRow.raw_text_hash,
            )
        ).all()
        return tuple(_to_source(r) for r in rows)

    # -- snapshots ---------------------------------------------------------

    def save_snapshot(
        self, organization_id: UUID, snapshot: IntentSnapshot
    ) -> IntentSnapshot:
        snapshot_uuid = parse_uuid(snapshot.snapshot_id, "snapshot_id")
        analysis_uuid = parse_uuid(snapshot.analysis_id, "analysis_id")
        parent_uuid = (
            parse_uuid(snapshot.parent_snapshot_id, "parent_snapshot_id")
            if snapshot.parent_snapshot_id is not None
            else None
        )
        created_at = require_aware(snapshot.created_at, "created_at")
        for criterion in snapshot.criteria:
            validate_criterion(criterion)
        self._require_analysis(organization_id, analysis_uuid)
        content_hash = snapshot_content_hash(snapshot)

        same = self._find_by_hash(organization_id, analysis_uuid, content_hash)
        if same is not None:
            return same

        source_rows = self._source_rows(organization_id, analysis_uuid)
        resolved: list[IntentSourceRow] = []
        for ref in snapshot.sources:
            row = source_rows.get((ref.kind.value, ref.source_id, ref.raw_text_hash))
            if row is None:
                msg = f"Source {ref.key} was not saved for this analysis."
                raise SourceNotFoundError(msg)
            resolved.append(row)
        by_key = {(r.kind, r.source_ref): r for r in resolved}

        if parent_uuid is not None:
            parent = self._session.scalar(
                select(IntentSnapshotRow.id).where(
                    IntentSnapshotRow.id == parent_uuid,
                    IntentSnapshotRow.organization_id == organization_id,
                    IntentSnapshotRow.analysis_id == analysis_uuid,
                )
            )
            if parent is None:
                msg = "Parent snapshot not found for this analysis."
                raise SnapshotNotFoundError(msg)

        try:
            with self._session.begin_nested():
                self._insert_snapshot(
                    organization_id,
                    snapshot,
                    snapshot_uuid,
                    analysis_uuid,
                    parent_uuid,
                    created_at,
                    content_hash,
                    resolved,
                    by_key,
                )
        except IntegrityError as exc:
            # Lost a race, or the id/version belongs to different content.
            raced = self._find_by_hash(organization_id, analysis_uuid, content_hash)
            if raced is not None:
                return raced
            msg = "A different snapshot already exists with this id or version."
            raise SnapshotConflictError(msg) from exc
        saved = self.get_snapshot(organization_id, snapshot.snapshot_id)
        if saved is None:  # pragma: no cover - defensive
            msg = "Snapshot could not be saved."
            raise SnapshotNotFoundError(msg)
        return saved

    def _find_by_hash(
        self, organization_id: UUID, analysis_id: UUID, content_hash: str
    ) -> IntentSnapshot | None:
        row = self._session.scalar(
            self._snapshot_query(organization_id).where(
                IntentSnapshotRow.analysis_id == analysis_id,
                IntentSnapshotRow.content_hash == content_hash,
            )
        )
        return _to_snapshot(row) if row is not None else None

    def _insert_snapshot(
        self,
        organization_id: UUID,
        snapshot: IntentSnapshot,
        snapshot_uuid: UUID,
        analysis_uuid: UUID,
        parent_uuid: UUID | None,
        created_at: datetime,
        content_hash: str,
        resolved: list[IntentSourceRow],
        by_key: dict[tuple[str, str], IntentSourceRow],
    ) -> None:
        self._session.add(
            IntentSnapshotRow(
                id=snapshot_uuid,
                organization_id=organization_id,
                analysis_id=analysis_uuid,
                version=snapshot.version,
                parent_snapshot_id=parent_uuid,
                content_hash=content_hash,
                created_at=created_at,
            )
        )
        self._session.flush()
        for position, source_row in enumerate(resolved):
            self._session.add(
                IntentSnapshotSourceRow(
                    organization_id=organization_id,
                    snapshot_id=snapshot_uuid,
                    source_row_id=source_row.id,
                    position=position,
                )
            )
        for position, criterion in enumerate(snapshot.criteria):
            source_row = by_key[
                (criterion.origin.source.kind.value, criterion.origin.source.source_id)
            ]
            self._session.add(
                IntentCriterionRow(
                    organization_id=organization_id,
                    snapshot_id=snapshot_uuid,
                    criterion_id=criterion.id,
                    position=position,
                    text=criterion.text,
                    normalized_text=criterion.normalized_text,
                    source_row_id=source_row.id,
                    origin_retrieved_at=as_utc(criterion.origin.retrieved_at),
                    extraction_method=criterion.origin.extraction_method.value,
                    extractor_version=criterion.origin.extractor_version,
                    span_start=criterion.span.start,
                    span_end=criterion.span.end,
                    weight=criterion.weight,
                    testability=criterion.testability.value,
                    testability_rationale=criterion.testability_rationale,
                    state=criterion.state.value,
                    hints=None,
                )
            )
        self._session.flush()

    def get_snapshot(
        self, organization_id: UUID, snapshot_id: str
    ) -> IntentSnapshot | None:
        snapshot_uuid = _try_uuid(snapshot_id)
        if snapshot_uuid is None:
            return None
        row = self._session.scalar(
            self._snapshot_query(organization_id).where(
                IntentSnapshotRow.id == snapshot_uuid
            )
        )
        return _to_snapshot(row) if row is not None else None

    def list_snapshots(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSnapshot, ...]:
        analysis_uuid = _try_uuid(analysis_id)
        if analysis_uuid is None:
            return ()
        rows = self._session.scalars(
            self._snapshot_query(organization_id)
            .where(IntentSnapshotRow.analysis_id == analysis_uuid)
            .order_by(IntentSnapshotRow.version)
        ).all()
        return tuple(_to_snapshot(r) for r in rows)

    def get_latest_snapshot(
        self, organization_id: UUID, analysis_id: str
    ) -> IntentSnapshot | None:
        analysis_uuid = _try_uuid(analysis_id)
        if analysis_uuid is None:
            return None
        row = self._session.scalar(
            self._snapshot_query(organization_id)
            .where(IntentSnapshotRow.analysis_id == analysis_uuid)
            .order_by(IntentSnapshotRow.version.desc())
            .limit(1)
        )
        return _to_snapshot(row) if row is not None else None

    # -- state changes -----------------------------------------------------

    def record_state_change(
        self,
        organization_id: UUID,
        snapshot_id: str,
        criterion_id: str,
        new_state: CriterionState,
        *,
        actor: str,
        changed_at: datetime,
        new_text: str | None = None,
        reason: str | None = None,
    ) -> Criterion:
        validate_actor(actor)
        changed_at = require_aware(changed_at, "changed_at")
        snapshot_uuid = _try_uuid(snapshot_id)
        if snapshot_uuid is None:
            msg = "Snapshot not found."
            raise SnapshotNotFoundError(msg)
        row = self._session.scalar(
            select(IntentCriterionRow)
            .where(
                IntentCriterionRow.organization_id == organization_id,
                IntentCriterionRow.snapshot_id == snapshot_uuid,
                IntentCriterionRow.criterion_id == criterion_id,
            )
            .options(selectinload(IntentCriterionRow.source))
        )
        if row is None:
            snapshot_exists = self._session.scalar(
                select(IntentSnapshotRow.id).where(
                    IntentSnapshotRow.id == snapshot_uuid,
                    IntentSnapshotRow.organization_id == organization_id,
                )
            )
            if snapshot_exists is None:
                msg = "Snapshot not found."
                raise SnapshotNotFoundError(msg)
            msg = "Criterion not found."
            raise CriterionNotFoundError(msg)
        current = _to_criterion(row)
        updated = apply_state_change(current, new_state, new_text)
        last = self._session.scalar(
            select(IntentCriterionStateChangeRow.sequence)
            .where(
                IntentCriterionStateChangeRow.organization_id == organization_id,
                IntentCriterionStateChangeRow.snapshot_id == snapshot_uuid,
                IntentCriterionStateChangeRow.criterion_id == criterion_id,
            )
            .order_by(IntentCriterionStateChangeRow.sequence.desc())
            .limit(1)
        )
        row.state = updated.state.value
        row.text = updated.text
        row.normalized_text = updated.normalized_text
        self._session.add(
            IntentCriterionStateChangeRow(
                organization_id=organization_id,
                snapshot_id=snapshot_uuid,
                criterion_id=criterion_id,
                sequence=(last or 0) + 1,
                old_state=current.state.value,
                new_state=updated.state.value,
                old_text=current.text if new_text is not None else None,
                new_text=new_text,
                actor=actor,
                reason=reason,
                changed_at=changed_at,
            )
        )
        self._session.flush()
        return updated

    def list_state_changes(
        self,
        organization_id: UUID,
        snapshot_id: str,
        criterion_id: str | None = None,
    ) -> tuple[CriterionStateChange, ...]:
        snapshot_uuid = _try_uuid(snapshot_id)
        if snapshot_uuid is None:
            return ()
        query = select(IntentCriterionStateChangeRow).where(
            IntentCriterionStateChangeRow.organization_id == organization_id,
            IntentCriterionStateChangeRow.snapshot_id == snapshot_uuid,
        )
        if criterion_id is not None:
            query = query.where(
                IntentCriterionStateChangeRow.criterion_id == criterion_id
            )
        rows = self._session.scalars(
            query.order_by(
                IntentCriterionStateChangeRow.changed_at,
                IntentCriterionStateChangeRow.criterion_id,
                IntentCriterionStateChangeRow.sequence,
            )
        ).all()
        return tuple(
            CriterionStateChange(
                snapshot_id=snapshot_id,
                criterion_id=r.criterion_id,
                old_state=CriterionState(r.old_state),
                new_state=CriterionState(r.new_state),
                actor=r.actor,
                changed_at=as_utc(r.changed_at),
                old_text=r.old_text,
                new_text=r.new_text,
                reason=r.reason,
            )
            for r in rows
        )


__all__ = ["SqlAlchemyIntentRepository"]
