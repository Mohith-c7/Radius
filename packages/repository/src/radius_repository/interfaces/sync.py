"""Repository synchronization interfaces."""

from typing import Protocol
from uuid import UUID


class RepositorySyncService(Protocol):
    """Contract for repository metadata synchronization."""

    def synchronize(self, repository_id: UUID) -> None:
        """Synchronize repository metadata."""
