"""Persistence port for the intent layer (IN-07).

Every method takes ``organization_id`` first and must scope all reads and
writes by it: an organization can never see, change or probe for another
organization's sources, snapshots or criteria. Lookups of data that belongs to
another organization behave exactly like lookups of missing data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from radius_intent.domain import (
    Criterion,
    CriterionState,
    IntentSnapshot,
    IntentSource,
)

#: Maximum UTF-8 size of one persisted source text (matches the IN-02 limit).
MAX_SOURCE_TEXT_BYTES = 64 * 1024


class IntentPersistenceError(Exception):
    """Base class for persistence failures."""


class InvalidIdentifierError(IntentPersistenceError, ValueError):
    """An id is not a canonical lowercase UUID string, or a value is unusable."""


class AnalysisNotFoundError(IntentPersistenceError):
    """The analysis does not exist for this organization."""


class SnapshotNotFoundError(IntentPersistenceError):
    """The snapshot (or its parent) does not exist for this organization."""


class CriterionNotFoundError(IntentPersistenceError):
    """The criterion does not exist in that snapshot for this organization."""


class SourceNotFoundError(IntentPersistenceError):
    """A snapshot cites a source that was not saved with ``save_sources``."""


class SourceTooLargeError(IntentPersistenceError, ValueError):
    """A source text exceeds :data:`MAX_SOURCE_TEXT_BYTES` or is not storable."""


class SnapshotConflictError(IntentPersistenceError):
    """A different snapshot already owns this id or (analysis, version)."""


@dataclass(frozen=True)
class CriterionStateChange:
    """One audited state transition (and wording change, for edits)."""

    snapshot_id: str
    criterion_id: str
    old_state: CriterionState
    new_state: CriterionState
    actor: str
    changed_at: datetime
    old_text: str | None = None
    new_text: str | None = None
    reason: str | None = None


class IntentRepository(Protocol):
    """Store intent sources, snapshots, criteria and their audit trail."""

    def save_sources(
        self,
        organization_id: UUID,
        analysis_id: str,
        sources: tuple[IntentSource, ...],
    ) -> None:
        """Store sources; idempotent per (kind, source_id, raw_text_hash)."""

    def get_sources(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSource, ...]:
        """Return stored sources ordered by (kind, source_id, raw_text_hash)."""

    def save_snapshot(
        self, organization_id: UUID, snapshot: IntentSnapshot
    ) -> IntentSnapshot:
        """Store a snapshot; saving identical content again returns the stored one."""

    def get_latest_snapshot(
        self, organization_id: UUID, analysis_id: str
    ) -> IntentSnapshot | None:
        """Return the highest-version snapshot, or ``None``."""

    def get_snapshot(
        self, organization_id: UUID, snapshot_id: str
    ) -> IntentSnapshot | None:
        """Return the snapshot, or ``None`` when absent for this organization."""

    def list_snapshots(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSnapshot, ...]:
        """Return all snapshots of the analysis, oldest version first."""

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
        """Apply a legal transition, append an audit row, return the criterion.

        ``new_text`` is required for (and only allowed with) ``EDITED``.
        """

    def list_state_changes(
        self,
        organization_id: UUID,
        snapshot_id: str,
        criterion_id: str | None = None,
    ) -> tuple[CriterionStateChange, ...]:
        """Return the audit trail, oldest first."""
