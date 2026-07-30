"""Repository domain value objects."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RepositoryId:
    """Stable Radius repository identifier."""

    value: UUID


@dataclass(frozen=True, slots=True)
class OrganizationId:
    """Stable Radius organization identifier."""

    value: UUID


@dataclass(frozen=True, slots=True)
class BranchName:
    """Git branch name."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Branch name cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CommitHash:
    """Git commit hash."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Commit hash cannot be empty."
            raise ValueError(msg)
        if len(self.value) > 40:
            msg = "Commit hash cannot exceed 40 characters."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RepositoryFullName:
    """Repository owner/name pair."""

    owner: str
    name: str

    def __post_init__(self) -> None:
        if not self.owner.strip():
            msg = "Repository owner cannot be empty."
            raise ValueError(msg)
        if not self.name.strip():
            msg = "Repository name cannot be empty."
            raise ValueError(msg)

    @property
    def value(self) -> str:
        """Return `owner/name`."""

        return f"{self.owner}/{self.name}"
