"""Database enum values for Phase 1 persistence."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Backport of Python 3.11 StrEnum for Python 3.9."""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


class UserRole(StrEnum):
    """Organization member role."""

    ADMIN = "admin"
    DEVELOPER = "developer"


class RepositoryProvider(StrEnum):
    """Source code hosting provider."""

    GITHUB = "github"


class RepositoryVisibility(StrEnum):
    """Repository visibility."""

    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


class RepositoryStatus(StrEnum):
    """Repository connection status."""

    CONNECTED = "connected"
    SYNCHRONIZING = "synchronizing"
    FAILED = "failed"
    DISCONNECTED = "disconnected"


class PullRequestStatus(StrEnum):
    """Pull request lifecycle status."""

    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class AnalysisStatus(StrEnum):
    """Analysis execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChangedFileType(StrEnum):
    """Git change type for a file."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class RiskLevel(StrEnum):
    """Confidence report risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalysisJobStatus(StrEnum):
    """Durable analysis job lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
