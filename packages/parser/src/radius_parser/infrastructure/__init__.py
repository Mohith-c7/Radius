"""Infrastructure adapters for the parser domain."""

from radius_parser.infrastructure.ecmascript_parser import (
    JavaScriptParser,
    TypeScriptParser,
)
from radius_parser.infrastructure.filesystem_discovery import (
    FilesystemSourceDiscovery,
)
from radius_parser.infrastructure.parser_registry import (
    StaticLanguageParserRegistry,
    default_language_parser_registry,
)
from radius_parser.infrastructure.python_parser import PythonAstParser

__all__ = [
    "FilesystemSourceDiscovery",
    "JavaScriptParser",
    "PythonAstParser",
    "StaticLanguageParserRegistry",
    "TypeScriptParser",
    "default_language_parser_registry",
]
