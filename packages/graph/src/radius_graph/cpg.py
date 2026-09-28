import posixpath

from radius_parser.models import Import, Reference, Symbol

from radius_graph.models import Node


def _file_matches_module(
    file_path: str, module_path: str, source_file: str | None = None
) -> bool:
    """Checks whether a symbol's file_path matches an import module_path."""
    fp = file_path.replace("\\", "/").rstrip("/")
    mp = module_path.replace("\\", "/").rstrip("/")

    # Strip known code file extensions from both
    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if fp.endswith(ext):
            fp = fp[: -len(ext)]
            break

    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if mp.endswith(ext):
            mp = mp[: -len(ext)]
            break

    # Handle python relative dot notation: .db -> ./db, ..db -> ../db
    if mp.startswith("."):
        dots = 0
        while dots < len(mp) and mp[dots] == ".":
            dots += 1
        rel_prefix = "../" * (dots - 1) if dots > 1 else "./"
        mp_rest = mp[dots:].replace(".", "/")
        mp = rel_prefix + mp_rest

    # Direct match or exact file basename / suffix match (e.g. "db" matches "src/db" or "db")
    if fp == mp or fp.endswith("/" + mp):
        return True

    # If source_file is provided and module_path is relative, resolve relative to source_file directory
    if source_file and (mp.startswith("./") or mp.startswith("../")):
        src_dir = posixpath.dirname(source_file.replace("\\", "/"))
        resolved_mp = posixpath.normpath(posixpath.join(src_dir, mp))
        if fp == resolved_mp or fp.endswith("/" + resolved_mp):
            return True

    # Dotted python module paths: e.g. "foo.bar" matches "foo/bar" or ".../foo/bar"
    mp_slashed = mp.replace(".", "/")
    if fp == mp_slashed or fp.endswith("/" + mp_slashed):
        return True

    # Index/init files: e.g. "db/__init__.py" or "db/index.ts" matches "db"
    if fp.endswith("/index") and (fp[:-6] == mp or fp[:-6].endswith("/" + mp)):
        return True
    if fp.endswith("/__init__") and (fp[:-9] == mp or fp[:-9].endswith("/" + mp)):
        return True

    return False


class CodePropertyGraph:
    """In-memory representation of the repository dependency graph."""

    def __init__(self):
        # Maps symbol_id to Node
        self.nodes: dict[str, Node] = {}
        self.file_imports: dict[str, list[Import]] = {}
        self._unresolved_references: list[Reference] = []

    def add_import(self, imp: Import) -> None:
        """Registers an import under its source file."""
        if imp.source_file not in self.file_imports:
            self.file_imports[imp.source_file] = []
        self.file_imports[imp.source_file].append(imp)

        # Re-attempt resolution of pending references
        pending = self._unresolved_references
        self._unresolved_references = []
        for ref in pending:
            if not self._resolve_reference(ref):
                self._unresolved_references.append(ref)

    def add_symbol(self, symbol: Symbol) -> None:
        """Registers a parsed symbol into the graph as a Node."""
        if symbol.id not in self.nodes:
            self.nodes[symbol.id] = Node(symbol=symbol)
            # Re-attempt resolution of pending references
            pending = self._unresolved_references
            self._unresolved_references = []
            for ref in pending:
                if not self._resolve_reference(ref):
                    self._unresolved_references.append(ref)

    def _resolve_reference(self, reference: Reference) -> bool:
        """Attempts to resolve a reference using import/module rules, same-file declarations, or global fallback.
        Returns True if resolved, False otherwise.
        """
        source_id = reference.source_symbol_id
        target_name = reference.target_name

        if source_id not in self.nodes:
            return False

        source_node = self.nodes[source_id]
        source_file = source_node.symbol.file_path

        target_id = None

        # 1. Check if reference.target_name matches an imported symbol in source_file
        matched_import = None
        imports = self.file_imports.get(source_file, []) if source_file else []
        for imp in imports:
            if (
                (imp.alias is not None and imp.alias == target_name)
                or (imp.alias is None and imp.imported_name == target_name)
                or (imp.imported_name == target_name)
            ):
                matched_import = imp
                break

        if matched_import:
            lookup_name = (
                matched_import.imported_name
                if matched_import.imported_name != "*"
                else target_name
            )
            # Exact match
            for node_id, node in self.nodes.items():
                if (
                    _file_matches_module(
                        node.symbol.file_path, matched_import.module_path, source_file
                    )
                    and node.symbol.name == lookup_name
                ):
                    target_id = node_id
                    break
            # Scoped match (e.g., Class.method)
            if not target_id:
                for node_id, node in self.nodes.items():
                    if _file_matches_module(
                        node.symbol.file_path, matched_import.module_path, source_file
                    ) and node.symbol.name.endswith("." + lookup_name):
                        target_id = node_id
                        break
        else:
            # 2. If not found in imports, check if target symbol is declared in the same source_file
            if source_file:
                for node_id, node in self.nodes.items():
                    if (
                        node.symbol.file_path == source_file
                        and node.symbol.name == target_name
                    ):
                        target_id = node_id
                        break
                if not target_id:
                    for node_id, node in self.nodes.items():
                        if (
                            node.symbol.file_path == source_file
                            and node.symbol.name.endswith("." + target_name)
                        ):
                            target_id = node_id
                            break

            # 3. If neither, fall back to global name match
            if not target_id:
                for node_id, node in self.nodes.items():
                    if node.symbol.name == target_name:
                        target_id = node_id
                        break
                if not target_id:
                    for node_id, node in self.nodes.items():
                        if node.symbol.name.endswith("." + target_name):
                            target_id = node_id
                            break

        if target_id:
            # Create the forward edge
            if target_id not in self.nodes[source_id].calls:
                self.nodes[source_id].calls.append(target_id)
            # Create the crucial backward edge (for blast radius slicing)
            if source_id not in self.nodes[target_id].called_by:
                self.nodes[target_id].called_by.append(source_id)
            return True

        return False

    def add_reference(self, reference: Reference) -> None:
        """Resolves a reference and creates bidirectional edges."""
        if not self._resolve_reference(reference):
            self._unresolved_references.append(reference)
