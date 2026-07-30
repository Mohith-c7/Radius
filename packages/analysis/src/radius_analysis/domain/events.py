"""Analysis domain events."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisStarted:
    """Emitted when an analysis is created."""

    analysis_id: UUID
    repository_id: UUID
    pull_request_id: UUID
    commit_sha: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisCompleted:
    """Emitted when an analysis reaches a terminal successful state."""

    analysis_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisFailed:
    """Emitted when an analysis reaches a terminal failed state."""

    analysis_id: UUID
    occurred_at: datetime
