"""Analysis domain value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommitSha:
    """Git commit SHA being verified."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Commit SHA cannot be empty."
            raise ValueError(msg)
        if len(self.value) > 40:
            msg = "Commit SHA cannot exceed 40 characters."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class FilePath:
    """Repository-relative file path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "File path cannot be empty."
            raise ValueError(msg)
        if self.value.startswith(("/", "\\")):
            msg = "File path must be repository-relative."
            raise ValueError(msg)
