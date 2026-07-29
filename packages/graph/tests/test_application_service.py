"""Graph application service tests."""

from pathlib import Path
from uuid import uuid4

from radius_graph.application import GraphApplicationService
from radius_graph.dto import BuildGraphCommand
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.domain import (
    ExportReference,
    FileChecksum,
    ImportReference,
    ParsedSourceFile,
    RepositoryParseResult,
    SourceFile,
    SourceLanguage,
    SourceLocation,
    SourcePath,
    Symbol,
    SymbolName,
    SymbolType,
    SymbolVisibility,
)


def test_build_graph_creates_file_symbol_import_and_export_edges() -> None:
    store = InMemoryGraphStore()
    service = GraphApplicationService(store)
    repository_id = uuid4()
    analysis_id = uuid4()

    response = service.build_graph(
        BuildGraphCommand(
            repository_id=repository_id,
            analysis_id=analysis_id,
            parse_result=_parse_result(),
        )
    )

    edge_types = {edge.edge_type for edge in response.edges}
    assert response.repository_id == repository_id
    assert response.analysis_id == analysis_id
    assert response.node_count == 5
    assert edge_types == {"contains", "depends_on", "imports", "exports"}
    assert store.get_snapshot(analysis_id).node_count == 5


def test_build_graph_skips_unparsed_source_files() -> None:
    service = GraphApplicationService()
    result = RepositoryParseResult(
        repository_path=Path("repo"),
        source_files=(
            SourceFile(
                path=SourcePath("README.md"),
                language=SourceLanguage.MARKDOWN,
                checksum=FileChecksum("a" * 64),
            ),
        ),
    )

    response = service.build_graph(
        BuildGraphCommand(
            repository_id=uuid4(),
            analysis_id=uuid4(),
            parse_result=result,
        )
    )

    assert response.node_count == 0
    assert response.edge_count == 0


def _parse_result() -> RepositoryParseResult:
    source_file = SourceFile(
        path=SourcePath("src/app.py"),
        language=SourceLanguage.PYTHON,
        checksum=FileChecksum("a" * 64),
    )
    parsed_file = ParsedSourceFile(
        source_file=source_file,
        symbols=(
            Symbol(
                name=SymbolName("main"),
                symbol_type=SymbolType.FUNCTION,
                visibility=SymbolVisibility.PUBLIC,
                location=SourceLocation(start_line=1),
            ),
        ),
        imports=(ImportReference(source="os"),),
        exports=(ExportReference(name="main"),),
    )
    return RepositoryParseResult(
        repository_path=Path("repo"),
        source_files=(source_file,),
        parsed_files=(parsed_file,),
    )
