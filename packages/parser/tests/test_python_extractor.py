import pytest
from radius_parser.core import ParserEngine
from radius_parser.extractors.python import PythonExtractor

def test_extract_symbols_and_calls():
    # Mock source code
    code = """
class Database:
    def query(self):
        return "data"

def get_user():
    db = Database()
    db.query()
    print("done")
"""
    # 1. Initialize our new Engine and Extractor
    engine = ParserEngine()
    tree = engine.parse_python(code)
    extractor = PythonExtractor()
    
    # 2. Extract Symbols (Classes and Functions)
    symbols = extractor.extract_symbols(tree.root_node, "test.py", code)
    
    assert len(symbols) == 3, f"Expected 3 symbols, got {len(symbols)}"
    
    # Check Class extraction
    assert symbols[0].name == "Database"
    assert symbols[0].type == "class"
    assert symbols[0].start_line == 2
    
    # Check Method extraction
    assert symbols[1].name == "Database.query"
    assert symbols[1].type == "function"
    assert symbols[1].start_line == 3
    assert symbols[1].end_line == 4
    
    # Check Function extraction
    get_user_symbol = symbols[2]
    assert get_user_symbol.name == "get_user"
    assert get_user_symbol.type == "function"
    assert get_user_symbol.start_line == 6
    assert get_user_symbol.end_line == 9
    
    # 3. Extract References (Function Calls) from the `get_user` function
    func_tree = engine.parse_python(get_user_symbol.source_code)
    calls = extractor.extract_calls(func_tree.root_node, get_user_symbol.id, get_user_symbol.source_code)
    
    call_names = [c.target_name for c in calls]
    
    assert "Database" in call_names, "Should detect the Database constructor call"
    assert "query" in call_names, "Should detect the db.query() attribute call"
    assert "print" in call_names, "Should detect the print() built-in call"
