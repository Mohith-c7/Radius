"""TypeScript import resolution over the fixture monorepo (F-09)."""

from pathlib import Path
from uuid import uuid4

import pytest
from radius_graph.application.services import GraphApplicationService
from radius_graph.domain.entities import DependencyGraph, GraphEdge, GraphNode
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId
from radius_graph.dto.commands import BuildGraphCommand
from radius_graph.infrastructure.module_resolver import ModuleResolver
from radius_graph.infrastructure.ts_resolver import TsModuleResolver
from radius_graph.traversal import file_dependents
from radius_parser.application.services import ParserApplicationService
from radius_parser.dto.commands import ParseRepositoryCommand
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)

FIXTURE = (
    Path(__file__).parents[2] / "parser" / "tests" / "fixtures" / "ts_monorepo"
)
WEB = "apps/web/src"


@pytest.fixture(scope="module")
def parse_result():
    return ParserApplicationService(
        FilesystemSourceDiscovery(), default_language_parser_registry()
    ).parse_repository_result(ParseRepositoryCommand(FIXTURE))


@pytest.fixture(scope="module")
def resolver(parse_result) -> TsModuleResolver:
    files = {item.source_file.path.value for item in parse_result.parsed_files}
    return TsModuleResolver(files, FIXTURE)


@pytest.mark.parametrize(
    ("importer", "specifier", "expected"),
    [
        # relative + extension/index resolution
        (f"{WEB}/main.tsx", "./lib", f"{WEB}/lib/index.ts"),
        (f"{WEB}/main.tsx", "./types", f"{WEB}/types.d.ts"),
        (f"{WEB}/main.tsx", "./legacy.cjs", f"{WEB}/legacy.cjs"),
        (f"{WEB}/lib/index.ts", "./a", f"{WEB}/lib/a.ts"),
        (f"{WEB}/components/Button.tsx", "../types", f"{WEB}/types.d.ts"),
        (f"{WEB}/components/Button.tsx", "../lib/a.js", f"{WEB}/lib/a.ts"),
        # app tsconfig: baseUrl=src, own paths, extends base (comments/commas)
        (f"{WEB}/main.tsx", "@/components/Button", f"{WEB}/components/Button.tsx"),
        (f"{WEB}/main.tsx", "@/lazy", f"{WEB}/lazy.ts"),
        (f"{WEB}/main.tsx", "components/Button", f"{WEB}/components/Button.tsx"),
        (f"{WEB}/esm.mjs", "@shared/util", "packages/shared/src/util.ts"),
        # shared package: its own tsconfig, extends base; baseUrl=src
        ("packages/shared/src/index.ts", "~/util", "packages/shared/src/util.ts"),
        # ui package: nearest tsconfig has paths but no baseUrl
        ("packages/ui/src/widget.ts", "~/helper", "packages/ui/src/helper.ts"),
    ],
)
def test_specifier_resolves(resolver, importer, specifier, expected) -> None:
    assert resolver.resolve(importer, specifier) == expected


def test_alias_is_scoped_to_the_nearest_tsconfig(resolver) -> None:
    # ``~/*`` exists in packages/shared and packages/ui only, and each maps to
    # its own src; the web app has no such alias.
    assert resolver.resolve(f"{WEB}/main.tsx", "~/util") is None
    assert resolver.resolve("packages/ui/src/widget.ts", "~/util") is None


@pytest.mark.parametrize("specifier", ["react", "lodash", "@scope/pkg", "node:fs"])
def test_bare_packages_are_external_not_errors(resolver, specifier) -> None:
    assert resolver.resolve(f"{WEB}/main.tsx", specifier) is None
    assert resolver.is_external(f"{WEB}/main.tsx", specifier)


def test_extends_cycle_and_malformed_config_do_not_crash(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"extends": "./b.json"}', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"extends": "./a.json"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text(
        '{"extends": "./a.json", "compilerOptions": {"baseUrl": "."}}',
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "tsconfig.json").write_text("{not json", encoding="utf-8")
    resolver = TsModuleResolver({"src/x.ts", "pkg/y.ts"}, tmp_path)

    # a malformed nearest config is skipped; the parent config governs
    assert resolver.resolve("pkg/y.ts", "src/x") == "src/x.ts"
    assert resolver.resolve("src/x.ts", "src/x") == "src/x.ts"  # baseUrl "."


def test_module_resolver_uses_ts_resolution_and_classifies_external(
    parse_result,
) -> None:
    module_resolver = ModuleResolver(
        parse_result.parsed_files, repository_path=FIXTURE
    )

    node = module_resolver.resolve(f"{WEB}/main.tsx", "@shared/util")
    assert node is not None
    assert node.value == "file:packages/shared/src/util.ts"
    assert module_resolver.is_external(f"{WEB}/main.tsx", "react")
    assert not module_resolver.is_external(f"{WEB}/main.tsx", "@/lazy")


def test_alias_imports_produce_graph_edges_and_file_dependents(
    parse_result,
) -> None:
    """Regression: edges via a tsconfig alias must reach impact analysis."""

    response = GraphApplicationService().build_graph(
        BuildGraphCommand(
            repository_id=uuid4(),
            analysis_id=uuid4(),
            parse_result=parse_result,
        )
    )
    graph = DependencyGraph(
        nodes=tuple(
            GraphNode(
                id=GraphNodeId(n.id),
                node_type=GraphNodeType(n.node_type),
                label=n.label,
                path=n.path,
            )
            for n in response.nodes
        ),
        edges=tuple(
            GraphEdge(
                source_id=GraphNodeId(e.source_id),
                target_id=GraphNodeId(e.target_id),
                edge_type=GraphEdgeType(e.edge_type),
            )
            for e in response.edges
        ),
    )
    depends = {
        (e.source_id, e.target_id) for e in response.edges if e.edge_type == "depends_on"
    }

    def edge(source: str, target: str) -> bool:
        return (f"file:{source}", f"file:{target}") in depends

    assert edge(f"{WEB}/main.tsx", f"{WEB}/components/Button.tsx")  # "@/..."
    assert edge(f"{WEB}/main.tsx", "packages/shared/src/util.ts")  # "@shared/..."
    assert edge(f"{WEB}/main.tsx", f"{WEB}/lazy.ts")  # dynamic import()
    assert edge(f"{WEB}/main.tsx", f"{WEB}/lib/index.ts")  # barrel
    assert edge(f"{WEB}/lib/index.ts", f"{WEB}/lib/b.ts")  # re-export
    assert not any(target.endswith("react") for _, target in depends if target.startswith("file:"))

    dependents = file_dependents(graph, ["packages/shared/src/util.ts"])[
        "packages/shared/src/util.ts"
    ]
    assert f"{WEB}/main.tsx" in dependents
    assert f"{WEB}/esm.mjs" in dependents
    assert "packages/shared/src/index.ts" in dependents
    # transitive through the barrel
    assert f"{WEB}/main.tsx" in file_dependents(
        graph, [f"{WEB}/lib/a.ts"]
    )[f"{WEB}/lib/a.ts"]
