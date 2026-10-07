import pytest
from radius_parser.core import ParserEngine
from radius_parser.extractors.typescript import TypeScriptExtractor


@pytest.fixture
def parser_setup():
    engine = ParserEngine()
    extractor = TypeScriptExtractor()
    return engine, extractor


def test_standard_function_declaration(parser_setup):
    engine, extractor = parser_setup
    code = "function calculateTotal(a: number, b: number) { return add(a, b); }"
    file_path = "src/calculator.ts"

    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    assert len(symbols) == 1
    func_sym = symbols[0]
    assert func_sym.id == f"{file_path}:calculateTotal"
    assert func_sym.name == "calculateTotal"
    assert func_sym.type == "function"
    assert func_sym.file_path == file_path
    assert func_sym.start_line == 1
    assert func_sym.end_line == 1
    assert func_sym.source_code == code

    func_tree = engine.parse_typescript(func_sym.source_code)
    calls = extractor.extract_calls(
        func_tree.root_node, func_sym.id, func_sym.source_code
    )

    call_names = [c.target_name for c in calls]
    assert "add" in call_names
    assert len(calls) == 1
    assert calls[0].source_symbol_id == func_sym.id
    assert calls[0].reference_type == "CALLS"


def test_class_declaration_and_methods(parser_setup):
    engine, extractor = parser_setup
    code = """class UserService {
    getUser(id: string) {
        return db.query(id);
    }
}"""
    file_path = "src/services/user.ts"

    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    assert len(symbols) == 2

    class_sym = symbols[0]
    assert class_sym.id == f"{file_path}:UserService"
    assert class_sym.name == "UserService"
    assert class_sym.type == "class"
    assert class_sym.file_path == file_path
    assert class_sym.start_line == 1
    assert class_sym.end_line == 5

    method_sym = symbols[1]
    assert method_sym.id == f"{file_path}:UserService.getUser"
    assert method_sym.name == "UserService.getUser"
    assert method_sym.type == "function"
    assert method_sym.file_path == file_path
    assert method_sym.start_line == 2
    assert method_sym.end_line == 4

    method_tree = engine.parse_typescript(method_sym.source_code)
    calls = extractor.extract_calls(
        method_tree.root_node, method_sym.id, method_sym.source_code
    )

    call_names = [c.target_name for c in calls]
    assert "query" in call_names
    assert "getUser" not in call_names


def test_arrow_function_assigned_to_const(parser_setup):
    engine, extractor = parser_setup
    code = "const processItem = (item: any) => { return transform(item); };"
    file_path = "src/utils.ts"

    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    assert len(symbols) == 1
    arrow_sym = symbols[0]
    assert arrow_sym.id == f"{file_path}:processItem"
    assert arrow_sym.name == "processItem"
    assert arrow_sym.type == "function"
    assert arrow_sym.file_path == file_path
    assert arrow_sym.start_line == 1
    assert arrow_sym.end_line == 1

    arrow_tree = engine.parse_typescript(arrow_sym.source_code)
    calls = extractor.extract_calls(
        arrow_tree.root_node, arrow_sym.id, arrow_sym.source_code
    )

    call_names = [c.target_name for c in calls]
    assert "transform" in call_names
    assert len(calls) == 1


def test_member_and_identifier_call_extraction(parser_setup):
    engine, extractor = parser_setup
    code = """function handleRequest() {
    client.fetchData();
    doSomething();
}"""
    file_path = "src/handler.ts"

    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    assert len(symbols) == 1
    handler_sym = symbols[0]

    calls = extractor.extract_calls(tree.root_node, handler_sym.id, code)
    call_names = [c.target_name for c in calls]

    assert "fetchData" in call_names
    assert "doSomething" in call_names
    assert len(calls) == 2


def test_nested_classes_and_multiline_positions(parser_setup):
    engine, extractor = parser_setup
    code = """
class OuterService {
    calculate() {
        class InnerHelper {
            run() {
                return true;
            }
        }
        return 42;
    }
}
"""
    file_path = "src/nested.ts"
    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    names = [s.name for s in symbols]
    assert "OuterService" in names
    assert "OuterService.calculate" in names
    assert "OuterService.calculate.InnerHelper" in names
    assert "OuterService.calculate.InnerHelper.run" in names

    sym_map = {s.name: s for s in symbols}
    assert sym_map["OuterService"].type == "class"
    assert sym_map["OuterService.calculate"].type == "function"
    assert sym_map["OuterService.calculate.InnerHelper"].type == "class"
    assert sym_map["OuterService.calculate.InnerHelper.run"].type == "function"

    assert sym_map["OuterService.calculate"].start_line == 3
    assert sym_map["OuterService.calculate"].end_line == 10
    assert sym_map["OuterService.calculate.InnerHelper"].start_line == 4
    assert sym_map["OuterService.calculate.InnerHelper"].end_line == 8
    assert sym_map["OuterService.calculate.InnerHelper.run"].start_line == 5
    assert sym_map["OuterService.calculate.InnerHelper.run"].end_line == 7


def test_exports_and_arrow_field_methods(parser_setup):
    engine, extractor = parser_setup
    code = """
export function exportedFunction() {
    helper();
}

export class ApiClient {
    public fetchData = (param: string) => {
        return doFetch(param);
    };
}

export const helper = () => {
    doSomething();
};
"""
    file_path = "src/api.ts"
    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    names = [s.name for s in symbols]
    assert "exportedFunction" in names
    assert "ApiClient" in names
    assert "ApiClient.fetchData" in names
    assert "helper" in names

    sym_map = {s.name: s for s in symbols}
    assert sym_map["exportedFunction"].type == "function"
    assert sym_map["ApiClient"].type == "class"
    assert sym_map["ApiClient.fetchData"].type == "function"
    assert sym_map["helper"].type == "function"


def test_constructor_new_expression_calls(parser_setup):
    engine, extractor = parser_setup
    code = """function initialize() {
    const db = new Database();
    const client = new api.Client();
    return db.connect();
}"""
    file_path = "src/init.ts"
    tree = engine.parse_typescript(code)
    symbols = extractor.extract_symbols(tree.root_node, file_path, code)

    assert len(symbols) == 1
    init_sym = symbols[0]

    calls = extractor.extract_calls(tree.root_node, init_sym.id, code)
    call_names = [c.target_name for c in calls]

    assert "Database" in call_names
    assert "Client" in call_names
    assert "connect" in call_names


def test_extract_imports(parser_setup):
    engine, extractor = parser_setup
    code = """
import { x } from './y';
import { a, b as c } from './z';
import defaultService from './service';
import * as utils from './utils';
import def, { specific, other as renamed } from './combined';
import './side-effect';
"""
    file_path = "src/main.ts"
    tree = engine.parse_typescript(code)
    imports = extractor.extract_imports(tree.root_node, file_path, code)

    assert len(imports) == 8

    # 1. named import: import { x } from './y'
    assert imports[0].source_file == file_path
    assert imports[0].imported_name == "x"
    assert imports[0].module_path == "./y"
    assert imports[0].alias is None

    # 2. named imports: import { a, b as c } from './z'
    assert imports[1].source_file == file_path
    assert imports[1].imported_name == "a"
    assert imports[1].module_path == "./z"
    assert imports[1].alias is None

    assert imports[2].source_file == file_path
    assert imports[2].imported_name == "b"
    assert imports[2].module_path == "./z"
    assert imports[2].alias == "c"

    # 3. default import: import defaultService from './service'
    assert imports[3].source_file == file_path
    assert imports[3].imported_name == "defaultService"
    assert imports[3].module_path == "./service"
    assert imports[3].alias is None

    # 4. namespace import: import * as utils from './utils'
    assert imports[4].source_file == file_path
    assert imports[4].imported_name == "*"
    assert imports[4].module_path == "./utils"
    assert imports[4].alias == "utils"

    # 5. combined import: import def, { specific, other as renamed } from './combined'
    assert imports[5].source_file == file_path
    assert imports[5].imported_name == "def"
    assert imports[5].module_path == "./combined"
    assert imports[5].alias is None

    assert imports[6].source_file == file_path
    assert imports[6].imported_name == "specific"
    assert imports[6].module_path == "./combined"
    assert imports[6].alias is None

    assert imports[7].source_file == file_path
    assert imports[7].imported_name == "other"
    assert imports[7].module_path == "./combined"
    assert imports[7].alias == "renamed"
