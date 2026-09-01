from radius_graph.models import Node
from radius_parser.models import Symbol, Reference

class CodePropertyGraph:
    """In-memory representation of the repository dependency graph."""
    
    def __init__(self):
        # Maps symbol_id to Node
        self.nodes: dict[str, Node] = {}
        
    def add_symbol(self, symbol: Symbol) -> None:
        """Registers a parsed symbol into the graph as a Node."""
        if symbol.id not in self.nodes:
            self.nodes[symbol.id] = Node(symbol=symbol)
            
    def add_reference(self, reference: Reference) -> None:
        """Resolves a reference and creates bidirectional edges."""
        source_id = reference.source_symbol_id
        target_name = reference.target_name
        
        if source_id not in self.nodes:
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
            self.nodes[source_id].calls.append(target_id)
            # Create the crucial backward edge (for blast radius slicing)
            self.nodes[target_id].called_by.append(source_id)
