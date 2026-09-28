from dataclasses import dataclass

@dataclass
class Symbol:
    """Represents a discrete structural entity in the codebase."""
    id: str  # A unique identifier, typically file_path + ":" + name
    name: str
    type: str  # e.g., 'function', 'class', 'method'
    file_path: str
    start_line: int
    end_line: int
    source_code: str

@dataclass
class Reference:
    """Represents a relationship from one symbol to another."""
    source_symbol_id: str
    target_name: str
    reference_type: str  # e.g., 'CALLS', 'IMPORTS'

@dataclass
class Import:
    """Represents an imported symbol from a module."""
    source_file: str
    imported_name: str
    module_path: str
    alias: str | None = None

