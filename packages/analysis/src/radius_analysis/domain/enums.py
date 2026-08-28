"""Analysis domain enum values."""

from enum import StrEnum


class AnalysisStatus(StrEnum):
    """Verification run lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChangedFileType(StrEnum):
    """Git file change type."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
