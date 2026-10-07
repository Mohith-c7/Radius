"""Go AST symbol and reference extractor using tree-sitter."""

from radius_parser.models import Import, Reference, Symbol
from tree_sitter import Node


class GoExtractor:
    """Extracts symbols and references from a Go AST."""

    def extract_symbols(
        self, root_node: Node, file_path: str, source_code: str
    ) -> list[Symbol]:
        """Traverses the Go AST to find functions, methods, structs, and interfaces."""
        symbols: list[Symbol] = []
        source_bytes = source_code.encode("utf8")

        for child in root_node.children:
            if child.type == "function_declaration":
                name_node = child.child_by_field_name("name")
                if name_node:
                    func_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    symbol_code = source_bytes[child.start_byte : child.end_byte].decode(
                        "utf8"
                    )
                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{func_name}",
                            name=func_name,
                            type="function",
                            file_path=file_path,
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                            source_code=symbol_code,
                        )
                    )

            elif child.type == "method_declaration":
                name_node = child.child_by_field_name("name")
                receiver_node = child.child_by_field_name("receiver")
                if name_node:
                    method_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    receiver_type = ""
                    if receiver_node:
                        # Extract receiver type name
                        rec_text = source_bytes[
                            receiver_node.start_byte : receiver_node.end_byte
                        ].decode("utf8")
                        # e.g. (s *Server) or (Server) -> Server
                        clean = rec_text.strip("()").split()[-1].lstrip("*")
                        receiver_type = clean

                    scoped_name = (
                        f"{receiver_type}.{method_name}"
                        if receiver_type
                        else method_name
                    )
                    symbol_code = source_bytes[child.start_byte : child.end_byte].decode(
                        "utf8"
                    )
                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{scoped_name}",
                            name=scoped_name,
                            type="method",
                            file_path=file_path,
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                            source_code=symbol_code,
                        )
                    )

            elif child.type == "type_declaration":
                for spec in child.children:
                    if spec.type == "type_spec":
                        name_node = spec.child_by_field_name("name")
                        type_node = spec.child_by_field_name("type")
                        if name_node:
                            type_name = source_bytes[
                                name_node.start_byte : name_node.end_byte
                            ].decode("utf8")
                            kind = "struct"
                            if type_node and type_node.type == "interface_type":
                                kind = "interface"
                            symbol_code = source_bytes[
                                child.start_byte : child.end_byte
                            ].decode("utf8")
                            symbols.append(
                                Symbol(
                                    id=f"{file_path}:{type_name}",
                                    name=type_name,
                                    type=kind,
                                    file_path=file_path,
                                    start_line=child.start_point[0] + 1,
                                    end_line=child.end_point[0] + 1,
                                    source_code=symbol_code,
                                )
                            )

        return symbols

    def extract_calls(
        self, root_node: Node, source_symbol_id: str, source_code: str
    ) -> list[Reference]:
        """Finds outgoing call expressions inside a Go symbol AST."""
        references: list[Reference] = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node):
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    if func_node.type == "selector_expression":
                        field_node = func_node.child_by_field_name("field")
                        if field_node:
                            target_name = source_bytes[
                                field_node.start_byte : field_node.end_byte
                            ].decode("utf8")
                            references.append(
                                Reference(source_symbol_id, target_name, "CALLS")
                            )
                    elif func_node.type == "identifier":
                        target_name = source_bytes[
                            func_node.start_byte : func_node.end_byte
                        ].decode("utf8")
                        references.append(
                            Reference(source_symbol_id, target_name, "CALLS")
                        )

            for child in node.children:
                traverse(child)

        traverse(root_node)
        return references

    def extract_imports(
        self, root_node: Node, file_path: str, source_code: str
    ) -> list[Import]:
        """Extracts import paths from a Go AST."""
        imports: list[Import] = []
        source_bytes = source_code.encode("utf8")

        def find_specs(node: Node):
            if node.type == "import_spec":
                path_node = node.child_by_field_name("path")
                alias_node = node.child_by_field_name("name")
                if path_node:
                    pkg_path = source_bytes[
                        path_node.start_byte : path_node.end_byte
                    ].decode("utf8").strip('"')
                    pkg_name = pkg_path.split("/")[-1]
                    alias = (
                        source_bytes[
                            alias_node.start_byte : alias_node.end_byte
                        ].decode("utf8")
                        if alias_node
                        else None
                    )
                    imports.append(
                        Import(
                            source_file=file_path,
                            imported_name=pkg_name,
                            module_path=pkg_path,
                            alias=alias,
                        )
                    )
                return
            for c in node.children:
                find_specs(c)

        for child in root_node.children:
            if child.type == "import_declaration":
                find_specs(child)

        return imports
