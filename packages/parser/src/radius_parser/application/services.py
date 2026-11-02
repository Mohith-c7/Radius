"""Parser application service."""

import logging
from pathlib import Path

from radius_shared.errors import ValidationError

from radius_parser.domain.entities import RepositoryParseResult, SourceFile
from radius_parser.dto.commands import ParseRepositoryCommand
from radius_parser.dto.responses import RepositoryParseResponse
from radius_parser.interfaces.discovery import SourceDiscovery
from radius_parser.interfaces.language_parser import LanguageParserRegistry

logger = logging.getLogger(__name__)


class ParserApplicationService:
    """Coordinates source discovery and language-specific parsing."""

    def __init__(
        self,
        discovery: SourceDiscovery,
        parser_registry: LanguageParserRegistry,
    ) -> None:
        self._discovery = discovery
        self._parser_registry = parser_registry

    def parse_repository(
        self,
        command: ParseRepositoryCommand,
    ) -> RepositoryParseResponse:
        """Parse a repository snapshot into normalized source metadata."""

        return RepositoryParseResponse.from_entity(
            self.parse_repository_result(command)
        )

    def parse_repository_result(
        self,
        command: ParseRepositoryCommand,
    ) -> RepositoryParseResult:
        """Parse a repository snapshot into a domain result."""

        repository_path = command.repository_path
        if not repository_path.exists() or not repository_path.is_dir():
            msg = f"Repository path does not exist: {repository_path}."
            raise ValidationError(msg)

        source_files = self._filter_changed_paths(
            self._discovery.discover(repository_path),
            command.changed_paths,
        )
        parsed_files = []
        parse_failures: list[str] = []
        experimental: set[str] = set()
        for source_file in source_files:
            parser = self._parser_registry.get_parser(source_file.language)
            if parser is None:
                continue
            if getattr(parser, "experimental", False):
                experimental.add(source_file.language.value)
            try:
                parsed_files.append(parser.parse(source_file))
            except (SyntaxError, UnicodeDecodeError, ValueError, OSError, RecursionError):
                # One malformed or binary file must not abort the whole
                # analysis; it is reported as missing evidence instead.
                parse_failures.append(source_file.path.value)

        if experimental:
            logger.warning(
                "Experimental parsers used for %s: imports are not resolved to "
                "files, so the dependency graph is incomplete for these languages.",
                ", ".join(sorted(experimental)),
            )

        result = RepositoryParseResult(
            repository_path=repository_path,
            source_files=tuple(source_files),
            parsed_files=tuple(parsed_files),
            parse_failures=tuple(parse_failures),
            experimental_languages=tuple(sorted(experimental)),
        )
        return result

    @staticmethod
    def _filter_changed_paths(
        source_files: list[SourceFile],
        changed_paths: tuple[str, ...] | None,
    ) -> list[SourceFile]:
        if changed_paths is None:
            return source_files

        selected = {Path(path).as_posix() for path in changed_paths}
        return [
            source_file
            for source_file in source_files
            if Path(source_file.path.value).as_posix() in selected
        ]
