"""Parser domain enum values."""

from enum import StrEnum


class SourceLanguage(StrEnum):
    """Source languages supported by Phase 1 discovery."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
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


class SymbolVisibility(StrEnum):
    """Normalized symbol visibility."""

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    UNKNOWN = "unknown"
