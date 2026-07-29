"""In-memory language parser registry."""

from radius_parser.domain.enums import SourceLanguage
from radius_parser.interfaces.language_parser import LanguageParser


class StaticLanguageParserRegistry:
    """Registry backed by a fixed parser collection."""

    def __init__(self, parsers: tuple[LanguageParser, ...] = ()) -> None:
        self._parsers = {
            parser.supported_language: parser for parser in parsers
        }

    def get_parser(self, language: SourceLanguage) -> LanguageParser | None:
        """Return a parser for a language when registered."""

        return self._parsers.get(language)
