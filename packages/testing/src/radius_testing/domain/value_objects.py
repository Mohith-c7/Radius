"""Testing domain value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TestPath:
    """Repository-relative test path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Test path cannot be empty."
            raise ValueError(msg)
        if self.value.startswith(("/", "\\")):
            msg = "Test path must be repository-relative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SourcePath:
    """Repository-relative source path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Source path cannot be empty."
            raise ValueError(msg)
        if self.value.startswith(("/", "\\")):
            msg = "Source path must be repository-relative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TestName:
    """Human-readable test name."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Test name cannot be empty."
            raise ValueError(msg)
