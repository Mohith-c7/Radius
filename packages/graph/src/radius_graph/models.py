from dataclasses import dataclass, field
from radius_parser.models import Symbol

@dataclass
class Node:
    """A Node in the Code Property Graph wrapping a parsed symbol."""
    symbol: Symbol
    # List of Node IDs that this node calls out to
    calls: list[str] = field(default_factory=list)
    # List of Node IDs that call into this node (Upstream dependencies)
    called_by: list[str] = field(default_factory=list)
