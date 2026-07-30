"""Repository domain events."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RepositoryConnected:
    """Emitted when a repository is connected."""

    repository_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RepositoryUpdated:
    """Emitted when repository metadata is updated."""

    repository_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RepositorySynchronizationStarted:
    """Emitted when repository synchronization starts."""

    repository_id: UUID
    occurred_at: datetime
