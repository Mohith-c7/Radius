"""External interfaces for the parser domain."""

from radius_parser.interfaces.discovery import SourceDiscovery
from radius_parser.interfaces.language_parser import (
    LanguageParser,
    LanguageParserRegistry,
)

__all__ = ["LanguageParser", "LanguageParserRegistry", "SourceDiscovery"]
