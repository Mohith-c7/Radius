"""Graph domain value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphNodeId:
    """Stable graph node identifier."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Graph node id cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GraphVersion:
    """Graph format or build version."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Graph version cannot be empty."
            raise ValueError(msg)
