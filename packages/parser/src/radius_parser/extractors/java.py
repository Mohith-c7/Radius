"""Java AST symbol and reference extractor using tree-sitter."""

from radius_parser.models import Import, Reference, Symbol
from tree_sitter import Node


class JavaExtractor:
    """Extracts symbols and references from a Java AST."""

    def extract_symbols(
        self, root_node: Node, file_path: str, source_code: str
    ) -> list[Symbol]:
        """Traverses the Java AST to find classes, interfaces, records, methods, and constructors."""
        symbols: list[Symbol] = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node, parent_scope: str = ""):
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
            ):
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
                    kind = "interface" if node.type == "interface_declaration" else "class"
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
                    # Traverse class body for methods
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            traverse(child, scoped_name)
                    return

            elif node.type in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    method_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf8")
                    scoped_name = (
                        f"{parent_scope}.{method_name}"
                        if parent_scope
                        else method_name
                    )
                    symbol_code = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf8"
                    )
                    symbols.append(
                        Symbol(
                            id=f"{file_path}:{scoped_name}",
                            name=scoped_name,
                            type="method",
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
        """Finds method invocations inside a Java AST."""
        references: list[Reference] = []
        source_bytes = source_code.encode("utf8")

        def traverse(node: Node):
            if node.type == "method_invocation":
                name_node = node.child_by_field_name("name")
                if name_node:
                    target_name = source_bytes[
                        name_node.start_byte : name_node.end_byte
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
        """Extracts imports from a Java AST."""
        imports: list[Import] = []
        source_bytes = source_code.encode("utf8")

        for child in root_node.children:
            if child.type == "import_declaration":
                # import java.util.List; or import static org.junit.Assert.*;
                text = source_bytes[child.start_byte : child.end_byte].decode("utf8")
                clean = text.replace("import", "").replace("static", "").replace(";", "").strip()
                imported_name = clean.split(".")[-1]
                imports.append(
                    Import(
                        source_file=file_path,
                        imported_name=imported_name,
                        module_path=clean,
                    )
                )
        return imports
