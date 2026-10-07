from radius_parser.models import Import, Reference, Symbol
from tree_sitter import Node


class PythonExtractor:
    """Extracts symbols and references from a Python AST."""

    def extract_symbols(
        self, root_node: Node, file_path: str, source_code: str
    ) -> list[Symbol]:
        """Traverses the AST to find function and class definitions."""
        symbols = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node, parent_scope: str = ""):
            if node.type in ("function_definition", "class_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    raw_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    # Append class/parent name for accurate namespacing
                    scoped_name = (
                        f"{parent_scope}.{raw_name}" if parent_scope else raw_name
                    )

                    symbol_code = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf8"
                    )
                    symbol_type = (
                        "function" if node.type == "function_definition" else "class"
                    )

                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{scoped_name}",
                            name=scoped_name,
                            type=symbol_type,
                            file_path=file_path,
                            # Tree-sitter lines are 0-indexed
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            source_code=symbol_code,
                        )
                    )

                    # Pass the scoped name down to children (e.g., methods inside this class)
                    for child in node.children:
                        traverse(child, scoped_name)
                    return  # Prevent double traversal

            for child in node.children:
                traverse(child, parent_scope)

        traverse(root_node)
        return symbols

    def extract_calls(
        self, root_node: Node, source_symbol_id: str, source_code: str
    ) -> list[Reference]:
        """Traverses a specific symbol's AST to find outgoing function calls."""
        references = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node):
            if node.type == "call":
                func_node = node.child_by_field_name("function")
                if func_node:
                    # In python, calls can be attributes (e.g. db.query) or identifiers (e.g. query)
                    if func_node.type == "attribute":
                        name_node = func_node.child_by_field_name("attribute")
                        if name_node:
                            target_name = source_bytes[
                                name_node.start_byte : name_node.end_byte
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
        """Traverses the AST to find import statements and extracts imported symbols."""
        imports = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node):
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        name = source_bytes[child.start_byte : child.end_byte].decode(
                            "utf8"
                        )
                        imports.append(
                            Import(
                                source_file=file_path,
                                imported_name=name,
                                module_path=name,
                                alias=None,
                            )
                        )
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        name = (
                            source_bytes[
                                name_node.start_byte : name_node.end_byte
                            ].decode("utf8")
                            if name_node
                            else ""
                        )
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
                                imported_name=name,
                                module_path=name,
                                alias=alias,
                            )
                        )
                return
            elif node.type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                module_path = (
                    source_bytes[module_node.start_byte : module_node.end_byte].decode(
                        "utf8"
                    )
                    if module_node
                    else ""
                )

                passed_import = False
                for child in node.children:
                    if child.type == "import":
                        passed_import = True
                        continue
                    if not passed_import:
                        continue
                    if child.type in ("dotted_name", "identifier"):
                        name = source_bytes[child.start_byte : child.end_byte].decode(
                            "utf8"
                        )
                        imports.append(
                            Import(
                                source_file=file_path,
                                imported_name=name,
                                module_path=module_path,
                                alias=None,
                            )
                        )
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        name = (
                            source_bytes[
                                name_node.start_byte : name_node.end_byte
                            ].decode("utf8")
                            if name_node
                            else ""
                        )
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
                                imported_name=name,
                                module_path=module_path,
                                alias=alias,
                            )
                        )
                    elif child.type == "wildcard_import":
                        imports.append(
                            Import(
                                source_file=file_path,
                                imported_name="*",
                                module_path=module_path,
                                alias=None,
                            )
                        )
                return

            for child in node.children:
                traverse(child)

        traverse(root_node)
        return imports
