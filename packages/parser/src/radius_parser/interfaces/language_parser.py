"""Language parser interfaces."""

from typing import Protocol

from radius_parser.domain.entities import ParsedSourceFile, SourceFile
from radius_parser.domain.enums import SourceLanguage


class LanguageParser(Protocol):
    """Contract for a language-specific source parser."""

    supported_language: SourceLanguage

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        """Parse one source file into normalized metadata."""


class LanguageParserRegistry(Protocol):
    """Contract for selecting language parsers."""

    def get_parser(self, language: SourceLanguage) -> LanguageParser | None:
        """Return a parser for a language when available."""
