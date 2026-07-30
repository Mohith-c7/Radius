"""Git provider client interfaces."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderRepository:
    """Repository metadata returned by a source provider."""

    github_repository_id: int
    name: str
    owner: str
    default_branch: str
    clone_url: str
    visibility: str


class GitProviderClient(Protocol):
    """Provider metadata contract for GitHub or future providers."""

    def get_repository(self, provider_repository_id: int) -> ProviderRepository:
        """Return repository metadata from the provider."""
