"""Coverage database enum values for Phase 1 persistence."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Backport of Python 3.11 StrEnum for Python 3.9."""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"
