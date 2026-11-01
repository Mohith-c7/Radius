"""Rust AST symbol and reference extractor using tree-sitter."""

from radius_parser.models import Import, Reference, Symbol
from tree_sitter import Node


class RustExtractor:
    """Extracts symbols and references from a Rust AST."""

    def extract_symbols(
        self, root_node: Node, file_path: str, source_code: str
    ) -> list[Symbol]:
        """Traverses the Rust AST to find functions, structs, enums, traits, and impl methods."""
        symbols: list[Symbol] = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node, parent_scope: str = ""):
            if node.type in ("struct_item", "enum_item", "trait_item"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    raw_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    scoped_name = (
                        f"{parent_scope}.{raw_name}" if parent_scope else raw_name
                    )
                    symbol_code = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf8"
                    )
                    kind = "struct" if node.type == "struct_item" else "enum" if node.type == "enum_item" else "trait"
                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{scoped_name}",
                            name=scoped_name,
                            type=kind,
                            file_path=file_path,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            source_code=symbol_code,
                        )
                    )
                    return

            elif node.type == "impl_item":
                # impl Config or impl Trait for Config
                type_node = node.child_by_field_name("type")
                impl_scope = ""
                if type_node:
                    impl_scope = source_bytes[
                        type_node.start_byte : type_node.end_byte
                    ].decode("utf8")
                body_node = node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        traverse(child, impl_scope)
                return

            elif node.type == "function_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    fn_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    scoped_name = (
                        f"{parent_scope}.{fn_name}" if parent_scope else fn_name
                    )
                    symbol_code = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf8"
                    )
                    kind = "method" if parent_scope else "function"
                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{scoped_name}",
                            name=scoped_name,
                            type=kind,
                            file_path=file_path,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            source_code=symbol_code,
                        )
                    )
                    return

            for child in node.children:
                traverse(child, parent_scope)

        traverse(root_node)
        return symbols

    def extract_calls(
        self, root_node: Node, source_symbol_id: str, source_code: str
    ) -> list[Reference]:
        """Finds outgoing calls inside a Rust AST."""
        references: list[Reference] = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node):
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    if func_node.type == "field_expression":
                        field_node = func_node.child_by_field_name("field")
                        if field_node:
                            target_name = source_bytes[
                                field_node.start_byte : field_node.end_byte
                            ].decode("utf8")
                            references.append(
                                Reference(source_symbol_id, target_name, "CALLS")
                            )
                    elif func_node.type == "scoped_identifier":
                        name_node = func_node.child_by_field_name("name")
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
        """Extracts use statements from a Rust AST."""
        imports: list[Import] = []
        source_bytes = source_code.encode("utf8")

        for child in root_node.children:
            if child.type == "use_declaration":
                # use std::collections::HashMap;
                text = source_bytes[child.start_byte : child.end_byte].decode("utf8")
                clean = text.replace("use", "").replace("pub", "").replace(";", "").strip()
                imported_name = clean.split("::")[-1].strip("{}")
                imports.append(
                    Import(
                        source_file=file_path,
                        imported_name=imported_name,
                        module_path=clean,
                    )
                )
        return imports
