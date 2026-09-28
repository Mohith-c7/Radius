import pytest
from radius_parser.models import Symbol, Reference, Import
from radius_graph.cpg import CodePropertyGraph
from radius_graph.slicer import GraphSlicer

def test_cpg_build_and_slice():
    # 1. Mock 3 symbols (A, B, C)
    symbol_c = Symbol("file:C", "C", "function", "file", 1, 5, "def C(): pass")
    symbol_b = Symbol("file:B", "B", "function", "file", 6, 10, "def B(): C()")
    symbol_a = Symbol("file:A", "A", "function", "file", 11, 15, "def A(): B()")
    
    # 2. Build the Graph
    cpg = CodePropertyGraph()
    cpg.add_symbol(symbol_c)
    cpg.add_symbol(symbol_b)
    cpg.add_symbol(symbol_a)
    
    # A calls B, B calls C
    cpg.add_reference(Reference("file:A", "B", "CALLS"))
    cpg.add_reference(Reference("file:B", "C", "CALLS"))
    
    # 3. Assert forward and backward edges
    node_c = cpg.nodes["file:C"]
    node_b = cpg.nodes["file:B"]
    node_a = cpg.nodes["file:A"]
    
    assert "file:B" in node_a.calls
    assert "file:A" in node_b.called_by
    assert "file:C" in node_b.calls
    assert "file:B" in node_c.called_by
    
    # 4. Test Slicer
    slicer = GraphSlicer(cpg)
    
    # If C changes, B and A should be in the blast radius
    slice_c = slicer.extract_caller_slice("file:C")
    affected_ids = [n.symbol.id for n in slice_c]
    
    assert len(affected_ids) == 2, f"Expected 2 affected callers, got {len(affected_ids)}"
    assert "file:B" in affected_ids
    assert "file:A" in affected_ids
    
    # If B changes, only A should be in the blast radius
    slice_b = slicer.extract_caller_slice("file:B")
    affected_ids_b = [n.symbol.id for n in slice_b]
    
    assert len(affected_ids_b) == 1
    assert "file:A" in affected_ids_b


def test_import_symbol_resolution():
    # Two files (db.py and search.py) both have a function named query
    db_query = Symbol(
        id="db.py:query",
        name="query",
        type="function",
        file_path="db.py",
        start_line=1,
        end_line=2,
        source_code="def query(): pass",
    )
    search_query = Symbol(
        id="search.py:query",
        name="query",
        type="function",
        file_path="search.py",
        start_line=1,
        end_line=2,
        source_code="def query(): pass",
    )
    service_func = Symbol(
        id="service.py:fetch_data",
        name="fetch_data",
        type="function",
        file_path="service.py",
        start_line=1,
        end_line=3,
        source_code="def fetch_data(): query()",
    )

    cpg = CodePropertyGraph()
    cpg.add_symbol(db_query)
    cpg.add_symbol(search_query)
    cpg.add_symbol(service_func)

    # service.py imports query from db
    cpg.add_import(Import(
        source_file="service.py",
        imported_name="query",
        module_path="db",
    ))

    # service.py calls query
    cpg.add_reference(Reference(
        source_symbol_id="service.py:fetch_data",
        target_name="query",
        reference_type="CALLS",
    ))

    service_node = cpg.nodes["service.py:fetch_data"]
    db_node = cpg.nodes["db.py:query"]
    search_node = cpg.nodes["search.py:query"]

    # Verify that the call resolves to db.py:query and NOT search.py:query
    assert "db.py:query" in service_node.calls
    assert "search.py:query" not in service_node.calls
    assert "service.py:fetch_data" in db_node.called_by
    assert "service.py:fetch_data" not in search_node.called_by

