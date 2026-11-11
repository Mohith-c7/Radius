"""In-memory language parser registry."""

from radius_parser.domain.enums import SourceLanguage
from radius_parser.interfaces.language_parser import LanguageParser


class StaticLanguageParserRegistry:
    """Registry backed by a fixed parser collection."""

    def __init__(self, parsers: tuple[LanguageParser, ...] = ()) -> None:
        self._parsers = {parser.supported_language: parser for parser in parsers}

    def get_parser(self, language: SourceLanguage) -> LanguageParser | None:
        """Return a parser for a language when registered."""

        return self._parsers.get(language)


def default_language_parser_registry() -> StaticLanguageParserRegistry:
    """Return the default Phase 1 parser registry."""

    from radius_parser.infrastructure.ecmascript_parser import (  # noqa: PLC0415
        JavaScriptParser,
        TypeScriptParser,
    )
    from radius_parser.infrastructure.python_parser import (
        PythonAstParser,  # noqa: PLC0415
    )
    parsers: list[LanguageParser] = [
        PythonAstParser(),
        JavaScriptParser(),
        TypeScriptParser(),
    ]
    try:
        from radius_parser.infrastructure.tree_sitter_parsers import (  # noqa: PLC0415
            GoLanguageParser,
            JavaLanguageParser,
            RustLanguageParser,
        )

        parsers.extend(
            [
                GoLanguageParser(),
                JavaLanguageParser(),
                RustLanguageParser(),
            ]
        )
    except (ImportError, ModuleNotFoundError):
        pass

    return StaticLanguageParserRegistry(tuple(parsers))
