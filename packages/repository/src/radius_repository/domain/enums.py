"""Repository domain enums."""

from enum import StrEnum


class RepositoryProvider(StrEnum):
    """Supported source code providers."""

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
    """Pull request lifecycle state."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
