"""Application-layer value objects: requests, reports and diff results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from radius_intent.domain import (
    Criterion,
    CriterionState,
    IntentSnapshot,
    IntentSourceKind,
)


class SnapshotBuildConflictError(Exception):
    """Concurrent builds kept colliding on the version; retries were exhausted."""


@dataclass(frozen=True)
class SourceRequest:
    """Ask the ``IntentSourceFetcher`` for one source."""

    kind: IntentSourceKind
    reference: str


@dataclass(frozen=True)
class Diagnostic:
    """Something worth knowing about a build that did not abort it."""

    code: str
    detail: str
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {"code": self.code, "source": self.source, "detail": self.detail}


@dataclass(frozen=True)
class CarryEvent:
    """What happened to one criterion that had a human decision attached.

    ``action`` is one of: carried, moved, needs_reconfirmation, orphaned,
    retained, restored.
    """

    action: str
    criterion_id: str
    previous_id: str | None
    state: CriterionState

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "action": self.action,
            "criterion_id": self.criterion_id,
            "previous_id": self.previous_id,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class BuildReport:
    """Diagnostics and carry-over events of one build."""

    diagnostics: tuple[Diagnostic, ...] = ()
    carry_events: tuple[CarryEvent, ...] = ()
    absent_sources: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "carry_events": [e.to_dict() for e in self.carry_events],
            "absent_sources": list(self.absent_sources),
        }


@dataclass(frozen=True)
class BuildResult:
    """Outcome of a build: the snapshot and whether a new version was made."""

    snapshot: IntentSnapshot
    created: bool
    report: BuildReport


@dataclass(frozen=True)
class CriterionSummary:
    """Compact, serializable view of a criterion."""

    criterion_id: str
    text: str
    state: str
    source: str

    @classmethod
    def of(cls, criterion: Criterion) -> CriterionSummary:
        """Summarize ``criterion``."""
        return cls(
            criterion.id,
            criterion.text,
            criterion.state.value,
            criterion.origin.source.key,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "criterion_id": self.criterion_id,
            "text": self.text,
            "state": self.state,
            "source": self.source,
        }


@dataclass(frozen=True)
class CriterionDelta:
    """A criterion present in both snapshots whose content or state differs."""

    criterion_id: str
    changed_fields: tuple[str, ...]
    text_before: str
    text_after: str
    state_before: str
    state_after: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "criterion_id": self.criterion_id,
            "changed_fields": list(self.changed_fields),
            "text_before": self.text_before,
            "text_after": self.text_after,
            "state_before": self.state_before,
            "state_after": self.state_after,
        }


@dataclass(frozen=True)
class SnapshotDiffResult:
    """Stable, serializable difference between two snapshots.

    All lists are sorted by criterion id. ``changed`` lists criteria whose
    substance changed (text, weight, testability, rationale, extraction
    method/version, source); ``state_changed`` those whose state differs (a
    criterion may be in both); ``moved`` criteria whose only change is the
    span (the source was edited around them).
    """

    from_snapshot_id: str
    to_snapshot_id: str
    from_version: int
    to_version: int
    added: tuple[CriterionSummary, ...]
    removed: tuple[CriterionSummary, ...]
    changed: tuple[CriterionDelta, ...]
    state_changed: tuple[CriterionDelta, ...]
    moved: tuple[str, ...]
    sources_added: tuple[str, ...]
    sources_removed: tuple[str, ...]
    sources_changed: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        """Return whether nothing differs."""
        return not (
            self.added
            or self.removed
            or self.changed
            or self.state_changed
            or self.moved
            or self.sources_added
            or self.sources_removed
            or self.sources_changed
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "from_snapshot_id": self.from_snapshot_id,
            "to_snapshot_id": self.to_snapshot_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "added": [c.to_dict() for c in self.added],
            "removed": [c.to_dict() for c in self.removed],
            "changed": [c.to_dict() for c in self.changed],
            "state_changed": [c.to_dict() for c in self.state_changed],
            "moved": list(self.moved),
            "sources_added": list(self.sources_added),
            "sources_removed": list(self.sources_removed),
            "sources_changed": list(self.sources_changed),
        }


__all__ = [
    "BuildReport",
    "BuildResult",
    "CarryEvent",
    "CriterionDelta",
    "CriterionSummary",
    "Diagnostic",
    "SnapshotBuildConflictError",
    "SnapshotDiffResult",
    "SourceRequest",
]
