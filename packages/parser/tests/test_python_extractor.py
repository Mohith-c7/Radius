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
    calls = extractor.extract_calls(
        func_tree.root_node, get_user_symbol.id, get_user_symbol.source_code
    )

    call_names = [c.target_name for c in calls]

    assert "Database" in call_names, "Should detect the Database constructor call"
    assert "query" in call_names, "Should detect the db.query() attribute call"
    assert "print" in call_names, "Should detect the print() built-in call"


def test_extract_imports():
    code = """
import os
import sys as system
import foo.bar
import foo.bar as fb
from math import sqrt, pi as PI
from .local import helper
from ..parent.module import something as s
from typing import *
"""
    engine = ParserEngine()
    tree = engine.parse_python(code)
    extractor = PythonExtractor()
    imports = extractor.extract_imports(tree.root_node, "test.py", code)

    assert len(imports) == 9

    # 1. import os
    assert imports[0].source_file == "test.py"
    assert imports[0].imported_name == "os"
    assert imports[0].module_path == "os"
    assert imports[0].alias is None

    # 2. import sys as system
    assert imports[1].source_file == "test.py"
    assert imports[1].imported_name == "sys"
    assert imports[1].module_path == "sys"
    assert imports[1].alias == "system"

    # 3. import foo.bar
    assert imports[2].source_file == "test.py"
    assert imports[2].imported_name == "foo.bar"
    assert imports[2].module_path == "foo.bar"
    assert imports[2].alias is None

    # 4. import foo.bar as fb
    assert imports[3].source_file == "test.py"
    assert imports[3].imported_name == "foo.bar"
    assert imports[3].module_path == "foo.bar"
    assert imports[3].alias == "fb"

    # 5. from math import sqrt
    assert imports[4].source_file == "test.py"
    assert imports[4].imported_name == "sqrt"
    assert imports[4].module_path == "math"
    assert imports[4].alias is None

    # 6. from math import pi as PI
    assert imports[5].source_file == "test.py"
    assert imports[5].imported_name == "pi"
    assert imports[5].module_path == "math"
    assert imports[5].alias == "PI"

    # 7. from .local import helper
    assert imports[6].source_file == "test.py"
    assert imports[6].imported_name == "helper"
    assert imports[6].module_path == ".local"
    assert imports[6].alias is None

    # 8. from ..parent.module import something as s
    assert imports[7].source_file == "test.py"
    assert imports[7].imported_name == "something"
    assert imports[7].module_path == "..parent.module"
    assert imports[7].alias == "s"

    # 9. from typing import *
    assert imports[8].source_file == "test.py"
    assert imports[8].imported_name == "*"
    assert imports[8].module_path == "typing"
    assert imports[8].alias is None
