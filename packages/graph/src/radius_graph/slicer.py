from radius_graph.cpg import CodePropertyGraph
from radius_graph.models import Node

class GraphSlicer:
    """Traverses the CPG to extract execution slices."""
    
    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        
    def extract_caller_slice(self, target_node_id: str) -> list[Node]:
        """
        Finds all upstream functions that depend on the target node.
        Uses BFS (Breadth-First Search) to walk backward up the call stack.
        """
        if target_node_id not in self.cpg.nodes:
            return []
            
        affected_nodes = []
        visited = set()
        queue = [target_node_id]
        
        while queue:
            current_id = queue.pop(0)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            # Add to slice if it's not the target node itself
            if current_id != target_node_id:
                affected_nodes.append(self.cpg.nodes[current_id])
                
            # Queue all callers
            for caller_id in self.cpg.nodes[current_id].called_by:
                if caller_id not in visited:
                    queue.append(caller_id)
                    
        return affected_nodes
