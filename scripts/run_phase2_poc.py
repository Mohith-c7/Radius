import os
import sys
from dotenv import load_dotenv

# Ensure packages are in PYTHONPATH
sys.path.append(os.path.abspath("packages/parser/src"))
sys.path.append(os.path.abspath("packages/graph/src"))
sys.path.append(os.path.abspath("packages/analysis/src"))

from radius_parser.core import ParserEngine
from radius_parser.extractors.python import PythonExtractor
from radius_graph.cpg import CodePropertyGraph
from radius_graph.slicer import GraphSlicer
from radius_analysis.ai.pruner import SemanticPruner

def main():
    load_dotenv()
    
    print("--- 1. PARSING REPOSITORY ---")
    engine = ParserEngine()
    extractor = PythonExtractor()
    cpg = CodePropertyGraph()
    
    # Parse our mock files
    for filename in ["db.py", "api.py"]:
        filepath = os.path.join("tmp/poc_repo", filename)
        with open(filepath, "r") as f:
            code = f.read()
            
        tree = engine.parse_python(code)
        symbols = extractor.extract_symbols(tree.root_node, filename, code)
        for sym in symbols:
            print(f"Extracted Symbol: {sym.id} ({sym.type})")
            cpg.add_symbol(sym)
            
            # Extract and add outbound function calls
            sym_tree = engine.parse_python(sym.source_code)
            calls = extractor.extract_calls(sym_tree.root_node, sym.id, sym.source_code)
            for call in calls:
                print(f"  -> Calls: {call.target_name}")
                cpg.add_reference(call)

    print("\n--- 2. GRAPH BUILT ---")
    
    print("\n--- 3. SIMULATING A BREAKING CHANGE IN db.py ---")
    # We are simulating a change where 'query' now requires a new argument, which breaks the caller.
    callee_diff = """
    class Database:
-       def query(self, id: int):
+       def query(self, id: int, strict_mode: bool):
-           return {'id': id, 'data': 'sensitive'}
+           if not strict_mode:
+               raise ValueError("strict_mode is now required!")
+           return {'id': id, 'data': 'sensitive'}
    """
    
    print("Target Node Modified: db.py:query")
    slicer = GraphSlicer(cpg)
    slice_nodes = slicer.extract_caller_slice("db.py:query")
    
    print("\n--- 4. CPG SLICER OUTPUT ---")
    for node in slice_nodes:
        print(f"Affected Caller found via Graph BFS: {node.symbol.id}")
        
    print("\n--- 5. SEMANTIC AI PRUNING ---")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Skipping AI Evaluation: GEMINI_API_KEY not found in environment. Please add it to your .env file.")
        return
        
    pruner = SemanticPruner(api_key=api_key)
    
    for node in slice_nodes:
        print(f"Evaluating impact on {node.symbol.id} using Gemini...")
        is_impacted = pruner.evaluate_impact(
            caller_source=node.symbol.source_code,
            callee_diff=callee_diff
        )
        if is_impacted:
            print(f"[RESULT] KEEP: {node.symbol.id} is genuinely broken by this change! (True Positive)")
        else:
            print(f"[RESULT] PRUNE: {node.symbol.id} is unaffected. (False Positive Pruned!)")

if __name__ == "__main__":
    main()
