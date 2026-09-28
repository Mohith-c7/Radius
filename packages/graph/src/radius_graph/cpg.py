from radius_graph.models import Node
from radius_parser.models import Symbol, Reference

class CodePropertyGraph:
    """In-memory representation of the repository dependency graph."""
    
    def __init__(self):
        # Maps symbol_id to Node
        self.nodes: dict[str, Node] = {}
        self._unresolved_references: list[Reference] = []
        
    def add_symbol(self, symbol: Symbol) -> None:
        """Registers a parsed symbol into the graph as a Node."""
        if symbol.id not in self.nodes:
            self.nodes[symbol.id] = Node(symbol=symbol)
            # Resolve any pending references matching this symbol
            still_unresolved = []
            for ref in self._unresolved_references:
                if ref.source_symbol_id in self.nodes and symbol.name == ref.target_name:
                    if symbol.id not in self.nodes[ref.source_symbol_id].calls:
                        self.nodes[ref.source_symbol_id].calls.append(symbol.id)
                    if ref.source_symbol_id not in self.nodes[symbol.id].called_by:
                        self.nodes[symbol.id].called_by.append(ref.source_symbol_id)
                else:
                    still_unresolved.append(ref)
            self._unresolved_references = still_unresolved
            
    def add_reference(self, reference: Reference) -> None:
        """Resolves a reference and creates bidirectional edges."""
        source_id = reference.source_symbol_id
        target_name = reference.target_name
        
        if source_id not in self.nodes:
            self._unresolved_references.append(reference)
            return
            
        # For this POC, we do O(N) lookup by name.
        # In production, this uses proper module import resolution rules.
        target_id = None
        for node_id, node in self.nodes.items():
            if node.symbol.name == target_name:
                target_id = node_id
                break
                
        if target_id:
            # Create the forward edge
            if target_id not in self.nodes[source_id].calls:
                self.nodes[source_id].calls.append(target_id)
            # Create the crucial backward edge (for blast radius slicing)
            if source_id not in self.nodes[target_id].called_by:
                self.nodes[target_id].called_by.append(source_id)
        else:
            self._unresolved_references.append(reference)
