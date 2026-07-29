"""Parser application service."""

from pathlib import Path

from radius_shared.errors import ValidationError

from radius_parser.domain.entities import RepositoryParseResult, SourceFile
from radius_parser.dto.commands import ParseRepositoryCommand
from radius_parser.dto.responses import RepositoryParseResponse
from radius_parser.interfaces.discovery import SourceDiscovery
from radius_parser.interfaces.language_parser import LanguageParserRegistry


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

        repository_path = command.repository_path
        if not repository_path.exists() or not repository_path.is_dir():
            msg = f"Repository path does not exist: {repository_path}."
            raise ValidationError(msg)

        source_files = self._filter_changed_paths(
            self._discovery.discover(repository_path),
            command.changed_paths,
        )
        parsed_files = []
        for source_file in source_files:
            parser = self._parser_registry.get_parser(source_file.language)
            if parser is None:
                continue
            parsed_files.append(parser.parse(source_file))

        result = RepositoryParseResult(
            repository_path=repository_path,
            source_files=tuple(source_files),
            parsed_files=tuple(parsed_files),
        )
        return RepositoryParseResponse.from_entity(result)

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
