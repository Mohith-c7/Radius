"""Graph domain enum values."""

from enum import StrEnum


class GraphNodeType(StrEnum):
    """Types of nodes in a Radius dependency graph."""

    FILE = "file"
    MODULE = "module"
    SYMBOL = "symbol"
    IMPORT = "import"
    EXPORT = "export"
    CLASS = "class"
    FUNCTION = "function"
    API = "api"
    DATABASE = "database"


class GraphEdgeType(StrEnum):
    """Types of relationships in a Radius dependency graph."""

    CONTAINS = "contains"
    IMPORTS = "imports"
    EXPORTS = "exports"
    DEFINES = "defines"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    DEPENDS_ON = "depends_on"
