"""Graph application command DTOs."""

from dataclasses import dataclass
from uuid import UUID

from radius_parser.domain.entities import RepositoryParseResult


@dataclass(frozen=True, slots=True)
class BuildGraphCommand:
    """Command to build a graph from parser output."""

    repository_id: UUID
    analysis_id: UUID
    parse_result: RepositoryParseResult
    graph_version: str = "v1"
