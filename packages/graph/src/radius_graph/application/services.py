"""Graph application service."""

from radius_parser.domain.entities import ParsedSourceFile

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion
from radius_graph.dto.commands import BuildGraphCommand
from radius_graph.dto.responses import GraphSnapshotResponse
from radius_graph.infrastructure.module_resolver import (
    ModuleResolver,
    load_tsconfig_aliases,
)
from radius_graph.interfaces.graph_store import GraphStore


class GraphApplicationService:
    """Builds deterministic repository relationship graphs."""

    def __init__(self, store: GraphStore | None = None) -> None:
        self._store = store

    def build_graph(self, command: BuildGraphCommand) -> GraphSnapshotResponse:
        """Build a graph snapshot from parser output."""

        nodes: dict[GraphNodeId, GraphNode] = {}
        edges: set[GraphEdge] = set()
        repository_path = command.parse_result.repository_path
        module_resolver = ModuleResolver(
            command.parse_result.parsed_files,
            path_aliases=(
                load_tsconfig_aliases(repository_path)
                if repository_path is not None and repository_path.is_dir()
                else None
            ),
        )

        for parsed_file in command.parse_result.parsed_files:
            self._add_parsed_file(parsed_file, nodes, edges, module_resolver)

        graph = DependencyGraph(
            nodes=tuple(nodes.values()),
            edges=tuple(sorted(edges, key=self._edge_sort_key)),
        )
        snapshot = GraphSnapshot(
            repository_id=command.repository_id,
            analysis_id=command.analysis_id,
            graph=graph,
            graph_version=GraphVersion(command.graph_version),
        )

        if self._store is not None:
            snapshot = self._store.save_snapshot(snapshot)

        return GraphSnapshotResponse.from_entity(snapshot)

    def _add_parsed_file(
        self,
        parsed_file: ParsedSourceFile,
        nodes: dict[GraphNodeId, GraphNode],
        edges: set[GraphEdge],
        module_resolver: ModuleResolver,
    ) -> None:
        file_path = parsed_file.source_file.path.value
        file_id = self.file_node_id(file_path)
        nodes[file_id] = GraphNode(
            id=file_id,
            node_type=GraphNodeType.FILE,
            label=file_path,
            path=file_path,
        )

        for symbol in parsed_file.symbols:
            symbol_id = self.symbol_node_id(file_path, symbol.name.value)
            nodes[symbol_id] = GraphNode(
                id=symbol_id,
                node_type=GraphNodeType.SYMBOL,
                label=symbol.name.value,
                path=file_path,
            )
            edges.add(
                GraphEdge(
                    source_id=file_id,
                    target_id=symbol_id,
                    edge_type=GraphEdgeType.CONTAINS,
                )
            )

        for item in parsed_file.imports:
            import_id = self.import_node_id(file_path, item.source)
            module_id = self.module_node_id(item.source)
            nodes[import_id] = GraphNode(
                id=import_id,
                node_type=GraphNodeType.IMPORT,
                label=item.source,
                path=file_path,
            )
            nodes.setdefault(
                module_id,
                GraphNode(
                    id=module_id,
                    node_type=GraphNodeType.MODULE,
                    label=item.source,
                ),
            )
            edges.add(
                GraphEdge(
                    source_id=file_id,
                    target_id=import_id,
                    edge_type=GraphEdgeType.IMPORTS,
                )
            )
            edges.add(
                GraphEdge(
                    source_id=import_id,
                    target_id=module_id,
                    edge_type=GraphEdgeType.DEPENDS_ON,
                )
            )
            for resolved_file_id in module_resolver.resolve_all(
                file_path,
                item.source,
                getattr(item, "names", ()),
            ):
                if resolved_file_id != file_id:
                    edges.add(
                        GraphEdge(
                            source_id=file_id,
                            target_id=resolved_file_id,
                            edge_type=GraphEdgeType.DEPENDS_ON,
                        )
                    )

        for item in parsed_file.exports:
            export_id = self.export_node_id(file_path, item.name)
            nodes[export_id] = GraphNode(
                id=export_id,
                node_type=GraphNodeType.EXPORT,
                label=item.name,
                path=file_path,
            )
            edges.add(
                GraphEdge(
                    source_id=file_id,
                    target_id=export_id,
                    edge_type=GraphEdgeType.EXPORTS,
                )
            )

    @staticmethod
    def file_node_id(path: str) -> GraphNodeId:
        """Return the stable node id for a file."""

        return GraphNodeId(f"file:{path}")

    @staticmethod
    def symbol_node_id(path: str, symbol_name: str) -> GraphNodeId:
        """Return the stable node id for a symbol."""

        return GraphNodeId(f"symbol:{path}:{symbol_name}")

    @staticmethod
    def import_node_id(path: str, source: str) -> GraphNodeId:
        """Return the stable node id for an import reference."""

        return GraphNodeId(f"import:{path}:{source}")

    @staticmethod
    def export_node_id(path: str, export_name: str) -> GraphNodeId:
        """Return the stable node id for an export reference."""

        return GraphNodeId(f"export:{path}:{export_name}")

    @staticmethod
    def module_node_id(source: str) -> GraphNodeId:
        """Return the stable node id for an imported module."""

        return GraphNodeId(f"module:{source}")

    @staticmethod
    def _edge_sort_key(edge: GraphEdge) -> tuple[str, str, str]:
        return (edge.source_id.value, edge.target_id.value, edge.edge_type.value)
