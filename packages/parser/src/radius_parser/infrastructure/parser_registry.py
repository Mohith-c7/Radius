"""In-memory language parser registry."""

from radius_parser.domain.enums import SourceLanguage
from radius_parser.interfaces.language_parser import LanguageParser

#: Languages whose parsers are experimental (DEC-017). Behaviour is unchanged;
#: imports are not resolved to repository files, so dependency edges for these
#: languages are missing evidence rather than a negative.
EXPERIMENTAL_LANGUAGES = frozenset(
    {SourceLanguage.GO, SourceLanguage.JAVA, SourceLanguage.RUST}
)


class StaticLanguageParserRegistry:
    """Registry backed by a fixed parser collection."""

    def __init__(self, parsers: tuple[LanguageParser, ...] = ()) -> None:
        self._parsers = {parser.supported_language: parser for parser in parsers}

    def get_parser(self, language: SourceLanguage) -> LanguageParser | None:
        """Return a parser for a language when registered."""

        return self._parsers.get(language)

    def is_experimental(self, language: SourceLanguage) -> bool:
        """Return whether the registered parser for ``language`` is experimental."""

        parser = self._parsers.get(language)
        return bool(getattr(parser, "experimental", False))


def default_language_parser_registry() -> StaticLanguageParserRegistry:
    """Return the default Phase 1 parser registry."""

    from radius_parser.infrastructure.ecmascript_parser import (  # noqa: PLC0415
        JavaScriptParser,
        TypeScriptParser,
    )
    from radius_parser.infrastructure.python_parser import (
        PythonAstParser,  # noqa: PLC0415
    )
    from radius_parser.infrastructure.tree_sitter_parsers import (  # noqa: PLC0415
        GoLanguageParser,
        JavaLanguageParser,
        RustLanguageParser,
    )

    return StaticLanguageParserRegistry(
        (
            PythonAstParser(),
            JavaScriptParser(),
            TypeScriptParser(),
            GoLanguageParser(),
            JavaLanguageParser(),
            RustLanguageParser(),
        )
    )
