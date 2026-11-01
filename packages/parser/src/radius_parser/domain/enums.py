"""Parser domain enum values."""

from enum import StrEnum


class SourceLanguage(StrEnum):
    """Source languages supported by Radius parser engine."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    GO = "go"
    JAVA = "java"
    RUST = "rust"
    JSON = "json"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class SymbolType(StrEnum):
    """Normalized source symbol type."""

    CLASS = "class"
    INTERFACE = "interface"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    ENUM = "enum"
    NAMESPACE = "namespace"
    STRUCT = "struct"
    TRAIT = "trait"


class SymbolVisibility(StrEnum):
    """Normalized symbol visibility."""

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    UNKNOWN = "unknown"
