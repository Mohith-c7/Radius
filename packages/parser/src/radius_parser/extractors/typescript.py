from tree_sitter import Node
from radius_parser.models import Symbol, Reference

class TypeScriptExtractor:
    """Extracts symbols and references from a TypeScript/JavaScript AST."""

    def extract_symbols(self, root_node: Node, file_path: str, source_code: str) -> list[Symbol]:
        """Traverses the TS AST to find function and class definitions."""
        symbols = []
        source_bytes = source_code.encode("utf8")
        
        def traverse(node: Node, parent_scope: str = ""):
            # Match TS specific node types
            if node.type in ('function_declaration', 'class_declaration', 'method_definition', 'arrow_function', 'function_expression'):
                # arrow_functions and function_expressions don't have a direct name field when anonymous/assigned
                if node.type in ('arrow_function', 'function_expression'):
                    if node.parent and node.parent.type in ('variable_declarator', 'public_field_definition', 'field_definition'):
                        name_node = node.parent.child_by_field_name('name') or node.parent.child_by_field_name('property')
                    else:
                        name_node = node.child_by_field_name('name')
                else:
                    name_node = node.child_by_field_name('name')
                    
                if name_node:
                    raw_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf8")
                    scoped_name = f"{parent_scope}.{raw_name}" if parent_scope else raw_name
                    
                    symbol_code = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                    symbol_type = "class" if node.type == 'class_declaration' else "function"
                    
                    symbols.append(Symbol(
                        id=f"{file_path}:{scoped_name}",
                        name=scoped_name,
                        type=symbol_type,
                        file_path=file_path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        source_code=symbol_code
                    ))
                    
                    for child in node.children:
                        traverse(child, scoped_name)
                    return
            
            for child in node.children:
                traverse(child, parent_scope)

        traverse(root_node)
        return symbols

    def extract_calls(self, root_node: Node, source_symbol_id: str, source_code: str) -> list[Reference]:
        """Traverses a specific symbol's TS AST to find outgoing function calls."""
        references = []
        source_bytes = source_code.encode("utf8")
        symbol_name = source_symbol_id.rsplit('.', 1)[-1].rsplit(':', 1)[-1]
        
        def traverse(node: Node):
            if node.type in ('call_expression', 'new_expression'):
                func_node = node.child_by_field_name('function') if node.type == 'call_expression' else node.child_by_field_name('constructor')
                if func_node:
                    # In TS, calls can be member_expressions (e.g. db.query) or identifiers (e.g. query)
                    if func_node.type == 'member_expression':
                        prop_node = func_node.child_by_field_name('property')
                        if prop_node:
                            target_name = source_bytes[prop_node.start_byte:prop_node.end_byte].decode("utf8")
                            references.append(Reference(source_symbol_id, target_name, "CALLS"))
                    elif func_node.type == 'identifier':
                        target_name = source_bytes[func_node.start_byte:func_node.end_byte].decode("utf8")
                        # Prevent standalone method declaration header misparsed as a call expression
                        is_misparsed_method_header = (
                            target_name == symbol_name
                            and (node.start_byte == 0 or node.has_error or (node.parent and node.parent.type == 'ERROR'))
                        )
                        if not is_misparsed_method_header:
                            references.append(Reference(source_symbol_id, target_name, "CALLS"))
                        
            for child in node.children:
                traverse(child)

        traverse(root_node)
        return references
