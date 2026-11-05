"""IntentSnapshot: the immutable set of criteria for an analysis at a time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from radius_intent.domain.criterion import Criterion
from radius_intent.domain.errors import DuplicateCriterionError, InvalidSnapshotError
from radius_intent.domain.value_objects import SourceRef


@dataclass(frozen=True)
class CriterionChange:
    """A criterion present in both snapshots whose content differs."""

    before: Criterion
    after: Criterion


@dataclass(frozen=True)
class SnapshotDiff:
    """Difference between two snapshots, matched by stable criterion id.

    ``added`` and ``changed`` follow the newer snapshot's order; ``removed``
    follows the older snapshot's order.
    """

    added: tuple[Criterion, ...]
    removed: tuple[Criterion, ...]
    changed: tuple[CriterionChange, ...]

    @property
    def is_empty(self) -> bool:
        """Return whether the snapshots are equivalent."""
        return not (self.added or self.removed or self.changed)


@dataclass(frozen=True)
class IntentSnapshot:
    """Immutable, ordered criteria for ``analysis_id`` at one version.

    Version 1 has no parent; every later version names its parent snapshot.
    ``created_at`` is supplied by the caller (no clock reads in the domain).
    """

    snapshot_id: str
    analysis_id: str
    version: int
    created_at: datetime
    criteria: tuple[Criterion, ...]
    sources: tuple[SourceRef, ...]
    parent_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.analysis_id.strip():
            raise InvalidSnapshotError("snapshot_id and analysis_id must be non-empty.")
        if self.created_at.tzinfo is None:
            raise InvalidSnapshotError("created_at must be timezone-aware.")
        if self.version < 1:
            raise InvalidSnapshotError("version must be >= 1.")
        if self.version == 1 and self.parent_snapshot_id is not None:
            raise InvalidSnapshotError("Version 1 must not have a parent snapshot.")
        if self.version > 1 and not self.parent_snapshot_id:
            raise InvalidSnapshotError("Versions after 1 require a parent snapshot.")
        if self.parent_snapshot_id == self.snapshot_id:
            raise InvalidSnapshotError("A snapshot cannot be its own parent.")
        object.__setattr__(self, "criteria", tuple(self.criteria))
        object.__setattr__(self, "sources", tuple(self.sources))
        known = {ref.key: ref for ref in self.sources}
        if len(known) != len(self.sources):
            raise InvalidSnapshotError("Duplicate source refs in snapshot.")
        seen: set[str] = set()
        for criterion in self.criteria:
            if criterion.id in seen:
                msg = f"Duplicate criterion id {criterion.id}."
                raise DuplicateCriterionError(msg)
            seen.add(criterion.id)
            ref = known.get(criterion.origin.source.key)
            if ref is None or ref != criterion.origin.source:
                msg = f"Criterion {criterion.id} cites a source not in the snapshot."
                raise InvalidSnapshotError(msg)

    def get(self, criterion_id: str) -> Criterion | None:
        """Return the criterion with ``criterion_id`` or ``None``."""
        for criterion in self.criteria:
            if criterion.id == criterion_id:
                return criterion
        return None

    def diff(self, newer: IntentSnapshot) -> SnapshotDiff:
        """Diff ``self`` (older) against ``newer`` by stable criterion id."""
        old = {c.id: c for c in self.criteria}
        new = {c.id: c for c in newer.criteria}
        added = tuple(c for c in newer.criteria if c.id not in old)
        removed = tuple(c for c in self.criteria if c.id not in new)
        changed = tuple(
            CriterionChange(old[c.id], c)
            for c in newer.criteria
            if c.id in old and old[c.id] != c
        )
        return SnapshotDiff(added=added, removed=removed, changed=changed)

    def next_version(
        self,
        snapshot_id: str,
        created_at: datetime,
        criteria: tuple[Criterion, ...],
        sources: tuple[SourceRef, ...],
    ) -> IntentSnapshot:
        """Build the child snapshot (version + 1, parent = this snapshot)."""
        return IntentSnapshot(
            snapshot_id=snapshot_id,
            analysis_id=self.analysis_id,
            version=self.version + 1,
            created_at=created_at,
            criteria=criteria,
            sources=sources,
            parent_snapshot_id=self.snapshot_id,
        )
