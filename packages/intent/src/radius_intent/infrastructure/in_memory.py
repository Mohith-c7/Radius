"""In-memory IntentRepository for tests and ``STORAGE_BACKEND=memory`` dev."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from uuid import UUID

from radius_intent.domain import (
    Criterion,
    CriterionState,
    IntentSnapshot,
    IntentSource,
)
from radius_intent.infrastructure.rules import (
    apply_state_change,
    parse_uuid,
    require_aware,
    snapshot_content_hash,
    validate_actor,
    validate_criterion,
    validate_source,
)
from radius_intent.interfaces.repository import (
    CriterionNotFoundError,
    CriterionStateChange,
    SnapshotConflictError,
    SnapshotNotFoundError,
    SourceNotFoundError,
)

_SourceKey = tuple[str, str, str]


@dataclass
class _Stored:
    organization_id: UUID
    snapshot: IntentSnapshot
    content_hash: str


def _source_key(source: IntentSource) -> _SourceKey:
    return (source.kind.value, source.source_id, source.raw_text_hash)


class InMemoryIntentRepository:
    """Thread-safe, process-local repository with the same semantics as SQL.

    It cannot verify that an analysis exists (there is no analyses table), so
    ``AnalysisNotFoundError`` is only raised by the SQL implementation.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # (org, analysis_id) -> source key -> source
        self._sources: dict[tuple[UUID, str], dict[_SourceKey, IntentSource]] = {}
        self._snapshots: dict[str, _Stored] = {}
        self._changes: list[tuple[UUID, int, CriterionStateChange]] = []

    def save_sources(
        self,
        organization_id: UUID,
        analysis_id: str,
        sources: tuple[IntentSource, ...],
    ) -> None:
        parse_uuid(analysis_id, "analysis_id")
        for source in sources:
            validate_source(source)
        with self._lock:
            bucket = self._sources.setdefault((organization_id, analysis_id), {})
            for source in sources:
                bucket.setdefault(_source_key(source), source)

    def get_sources(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSource, ...]:
        with self._lock:
            bucket = self._sources.get((organization_id, analysis_id), {})
            return tuple(bucket[key] for key in sorted(bucket))

    def save_snapshot(
        self, organization_id: UUID, snapshot: IntentSnapshot
    ) -> IntentSnapshot:
        parse_uuid(snapshot.snapshot_id, "snapshot_id")
        parse_uuid(snapshot.analysis_id, "analysis_id")
        if snapshot.parent_snapshot_id is not None:
            parse_uuid(snapshot.parent_snapshot_id, "parent_snapshot_id")
        require_aware(snapshot.created_at, "created_at")
        for criterion in snapshot.criteria:
            validate_criterion(criterion)
        content_hash = snapshot_content_hash(snapshot)
        with self._lock:
            known = self._sources.get((organization_id, snapshot.analysis_id), {})
            for ref in snapshot.sources:
                if (ref.kind.value, ref.source_id, ref.raw_text_hash) not in known:
                    msg = f"Source {ref.key} was not saved for this analysis."
                    raise SourceNotFoundError(msg)
            mine = [
                s
                for s in self._snapshots.values()
                if s.organization_id == organization_id
                and s.snapshot.analysis_id == snapshot.analysis_id
            ]
            for stored in mine:
                if stored.content_hash == content_hash:
                    return stored.snapshot
            if snapshot.snapshot_id in self._snapshots or any(
                s.snapshot.version == snapshot.version for s in mine
            ):
                msg = "A different snapshot already exists with this id or version."
                raise SnapshotConflictError(msg)
            if snapshot.parent_snapshot_id is not None and not any(
                s.snapshot.snapshot_id == snapshot.parent_snapshot_id for s in mine
            ):
                msg = "Parent snapshot not found for this analysis."
                raise SnapshotNotFoundError(msg)
            self._snapshots[snapshot.snapshot_id] = _Stored(
                organization_id, snapshot, content_hash
            )
            return snapshot

    def _mine(self, organization_id: UUID, analysis_id: str) -> list[IntentSnapshot]:
        found = [
            s.snapshot
            for s in self._snapshots.values()
            if s.organization_id == organization_id
            and s.snapshot.analysis_id == analysis_id
        ]
        return sorted(found, key=lambda s: s.version)

    def get_latest_snapshot(
        self, organization_id: UUID, analysis_id: str
    ) -> IntentSnapshot | None:
        with self._lock:
            found = self._mine(organization_id, analysis_id)
            return found[-1] if found else None

    def get_snapshot(
        self, organization_id: UUID, snapshot_id: str
    ) -> IntentSnapshot | None:
        with self._lock:
            stored = self._snapshots.get(snapshot_id)
            if stored is None or stored.organization_id != organization_id:
                return None
            return stored.snapshot

    def list_snapshots(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSnapshot, ...]:
        with self._lock:
            return tuple(self._mine(organization_id, analysis_id))

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
        with self._lock:
            stored = self._snapshots.get(snapshot_id)
            if stored is None or stored.organization_id != organization_id:
                msg = "Snapshot not found."
                raise SnapshotNotFoundError(msg)
            current = stored.snapshot.get(criterion_id)
            if current is None:
                msg = "Criterion not found."
                raise CriterionNotFoundError(msg)
            updated = apply_state_change(current, new_state, new_text)
            criteria = tuple(
                updated if c.id == criterion_id else c for c in stored.snapshot.criteria
            )
            stored.snapshot = replace(stored.snapshot, criteria=criteria)
            sequence = 1 + sum(
                1
                for org, _, c in self._changes
                if org == organization_id
                and c.snapshot_id == snapshot_id
                and c.criterion_id == criterion_id
            )
            self._changes.append(
                (
                    organization_id,
                    sequence,
                    CriterionStateChange(
                        snapshot_id=snapshot_id,
                        criterion_id=criterion_id,
                        old_state=current.state,
                        new_state=new_state,
                        actor=actor,
                        changed_at=changed_at,
                        old_text=current.text if new_text is not None else None,
                        new_text=new_text,
                        reason=reason,
                    ),
                )
            )
            return updated

    def list_state_changes(
        self,
        organization_id: UUID,
        snapshot_id: str,
        criterion_id: str | None = None,
    ) -> tuple[CriterionStateChange, ...]:
        with self._lock:
            rows = [
                (change, sequence)
                for org, sequence, change in self._changes
                if org == organization_id
                and change.snapshot_id == snapshot_id
                and (criterion_id is None or change.criterion_id == criterion_id)
            ]
            rows.sort(key=lambda r: (r[0].changed_at, r[0].criterion_id, r[1]))
            return tuple(change for change, _ in rows)


__all__ = ["InMemoryIntentRepository"]
