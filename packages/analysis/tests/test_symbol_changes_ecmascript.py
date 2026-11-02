"""LK-01: table-driven TypeScript / JavaScript symbol-change cases (F-09 tree-sitter parser)."""

from __future__ import annotations

import pytest

from .symbol_changes_helpers import run, summary

F = "function"
M = "method"
C = "class"

LONG = (
    "  let total = 0;\n"
    "  for (const item of items) {\n"
    "    if (item.active && item.price > 0) {\n"
    "      total += item.price * item.qty;\n"
    "    }\n"
    "  }\n"
    "  return Math.round(total * 100) / 100;\n"
)

# (case id, path, base, head, expected {(qualified_name, kind, change_kind)})
CASES: list[tuple[str, str, str, str, set[tuple[str, str, str]]]] = [
    (
        "function_body",
        "src/a.ts",
        "export function f(a: number) {\n  return a + 1;\n}\n",
        "export function f(a: number) {\n  return a + 2;\n}\n",
        {("f", F, "modified_body")},
    ),
    (
        "function_param_type",
        "src/a.ts",
        "export function f(a: number) {\n  return a;\n}\n",
        "export function f(a: string) {\n  return a;\n}\n",
        {("f", F, "modified_signature")},
    ),
    (
        "function_return_type",
        "src/a.ts",
        "function f(a: number) {\n  return a;\n}\n",
        "function f(a: number): number {\n  return a;\n}\n",
        {("f", F, "modified_signature")},
    ),
    (
        "export_keyword_added",
        "src/a.ts",
        "function f() {\n  return 1;\n}\n",
        "export function f() {\n  return 1;\n}\n",
        {("f", F, "modified_signature")},
    ),
    (
        "arrow_const_body",
        "src/a.ts",
        "export const h = (x: number) => x * 2;\n",
        "export const h = (x: number) => x * 3;\n",
        {("h", F, "modified_body")},
    ),
    (
        "arrow_const_params",
        "src/a.ts",
        "export const h = (x: number) => x * 2;\n",
        "export const h = (x: number, y: number) => x * 2;\n",
        {("h", F, "modified_signature")},
    ),
    (
        "async_arrow_added",
        "src/a.ts",
        "export const A = 1;\n",
        "export const A = 1;\nexport const load = async (id: string) => fetch(id);\n",
        {("load", F, "added")},
    ),
    (
        "function_expression_const",
        "src/a.js",
        "const g = function (a) {\n  return a;\n};\n",
        "const g = function (a) {\n  return a + 1;\n};\n",
        {("g", F, "modified_body")},
    ),
    (
        "class_method_body",
        "src/a.ts",
        "export class K {\n  x = 1;\n  m() {\n    return 1;\n  }\n}\n",
        "export class K {\n  x = 1;\n  m() {\n    return 2;\n  }\n}\n",
        {("K.m", M, "modified_body")},
    ),
    (
        "class_field_changed",
        "src/a.ts",
        "export class K {\n  x = 1;\n  m() {\n    return 1;\n  }\n}\n",
        "export class K {\n  x = 2;\n  m() {\n    return 1;\n  }\n}\n",
        {("K", C, "modified_body")},
    ),
    (
        "class_extends_changed",
        "src/a.ts",
        "export class K extends A {\n  m() {\n    return 1;\n  }\n}\n",
        "export class K extends B {\n  m() {\n    return 1;\n  }\n}\n",
        {("K", C, "modified_signature")},
    ),
    (
        "method_added_to_class",
        "src/a.ts",
        "export class K {\n  m() {\n    return 1;\n  }\n}\n",
        "export class K {\n  m() {\n    return 1;\n  }\n  n() {\n    return 2;\n  }\n}\n",
        {("K.n", M, "added")},
    ),
    (
        "class_added_with_methods",
        "src/a.ts",
        "export const X = 1;\n",
        "export const X = 1;\nexport class K {\n  a() {\n    return 1;\n  }\n  b() {\n    return 2;\n  }\n}\n",
        {("K", C, "added"), ("K.a", M, "added"), ("K.b", M, "added")},
    ),
    (
        "class_removed_with_methods",
        "src/a.ts",
        "export const X = 1;\nexport class K {\n  a() {\n    return 1;\n  }\n}\n",
        "export const X = 1;\n",
        {("K", C, "removed"), ("K.a", M, "removed")},
    ),
    (
        "static_and_private_methods",
        "src/a.ts",
        "class K {\n  static s() {\n    return 1;\n  }\n  #p() {\n    return 1;\n  }\n}\n",
        "class K {\n  static s() {\n    return 2;\n  }\n  #p() {\n    return 1;\n  }\n}\n",
        {("K.s", M, "modified_body")},
    ),
    (
        "accessor_pair",
        "src/a.ts",
        "class K {\n  get v() {\n    return 1;\n  }\n  set v(x: number) {}\n}\n",
        "class K {\n  get v() {\n    return 2;\n  }\n  set v(x: number) {}\n}\n",
        {("K.v.get", "property", "modified_body")},
    ),
    (
        "arrow_class_field",
        "src/a.ts",
        "class K {\n  handler = (e: Event) => {\n    return 1;\n  };\n}\n",
        "class K {\n  handler = (e: Event) => {\n    return 2;\n  };\n}\n",
        {("K.handler", M, "modified_body")},
    ),
    (
        "interface_member_added",
        "src/a.ts",
        "export interface I {\n  a: number;\n}\n",
        "export interface I {\n  a: number;\n  b: string;\n}\n",
        {("I", "interface", "modified_body")},
    ),
    (
        "type_alias_changed",
        "src/a.ts",
        "export type T = { a: number };\n",
        "export type T = { a: number; b: string };\n",
        {("T", "type", "modified_body")},
    ),
    (
        "enum_member_added",
        "src/a.ts",
        "export enum E {\n  A,\n  B,\n}\n",
        "export enum E {\n  A,\n  B,\n  C,\n}\n",
        {("E", "enum", "modified_body")},
    ),
    (
        "interface_added",
        "src/a.ts",
        "export const X = 1;\n",
        "export const X = 1;\ninterface P {\n  id: string;\n}\n",
        {("P", "interface", "added")},
    ),
    (
        "class_decorator_changed",
        "src/a.ts",
        "@Component({ selector: 'a' })\nexport class K {\n  x = 1;\n}\n",
        "@Component({ selector: 'b' })\nexport class K {\n  x = 1;\n}\n",
        {("K", C, "decorator_or_annotation_changed")},
    ),
    (
        "method_decorator_added",
        "src/a.ts",
        "class K {\n  m() {\n    return 1;\n  }\n}\n",
        "class K {\n  @Log()\n  m() {\n    return 1;\n  }\n}\n",
        {("K.m", M, "decorator_or_annotation_changed")},
    ),
    (
        "jsdoc_only",
        "src/a.ts",
        "/** Adds one. */\nexport function f(a: number) {\n  return a + 1;\n}\n",
        "/** Adds exactly one. */\nexport function f(a: number) {\n  return a + 1;\n}\n",
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "inline_comment_only",
        "src/a.ts",
        "export function f(a: number) {\n  return a + 1;\n}\n",
        "export function f(a: number) {\n  // plus one\n  return a + 1;\n}\n",
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "formatting_semicolons_quotes_commas",
        "src/a.ts",
        "export function f(a: number) {\n  const s = 'x'\n  return g(s, a)\n}\n",
        'export function f(a: number) {\n  const s = "x";\n  return g(\n    s,\n    a,\n  );\n}\n',
        {("f", F, "formatting_only")},
    ),
    (
        "formatting_indentation",
        "src/a.ts",
        "export function f(a: number) {\nreturn a + 1;\n}\n",
        "export function f(a: number) {\n    return a + 1;\n}\n",
        {("f", F, "formatting_only")},
    ),
    (
        "nested_function_changed",
        "src/a.ts",
        "function outer() {\n  function inner() {\n    return 1;\n  }\n  return inner;\n}\n",
        "function outer() {\n  function inner() {\n    return 2;\n  }\n  return inner;\n}\n",
        {("outer.<locals>.inner", F, "modified_body")},
    ),
    (
        "overload_signature_added",
        "src/a.ts",
        "function o(a: string): void;\nfunction o(a: any) {}\n",
        "function o(a: string): void;\nfunction o(a: number): void;\nfunction o(a: any) {}\n",
        {("o@2", F, "added")},
    ),
    (
        "generator_function",
        "src/a.js",
        "function* gen() {\n  yield 1;\n}\n",
        "function* gen() {\n  yield 2;\n}\n",
        {("gen", F, "modified_body")},
    ),
    (
        "namespace_member",
        "src/a.ts",
        "namespace N {\n  export function h() {\n    return 1;\n  }\n}\n",
        "namespace N {\n  export function h() {\n    return 2;\n  }\n}\n",
        {("N.h", F, "modified_body")},
    ),
    (
        "module_level_statement",
        "src/a.ts",
        "export const LIMIT = 10;\nexport function f() {\n  return LIMIT;\n}\n",
        "export const LIMIT = 20;\nexport function f() {\n  return LIMIT;\n}\n",
        {("<module>", "module", "modified_body")},
    ),
    (
        "test_callbacks_are_module_level",
        "src/a.test.ts",
        "describe('a', () => {\n  it('works', () => {\n    expect(f()).toBe(1);\n  });\n});\n",
        "describe('a', () => {\n  it('works', () => {\n    expect(f()).toBeTruthy();\n  });\n});\n",
        {("<module>", "module", "modified_body")},
    ),
    (
        "tsx_component",
        "src/App.tsx",
        "export function App() {\n  return <div className=\"a\">hi</div>;\n}\n",
        "export function App() {\n  return <div className=\"b\">hi</div>;\n}\n",
        {("App", F, "modified_body")},
    ),
    (
        "jsx_formatting",
        "src/App.jsx",
        "export function App() {\n  return <div>hi   there</div>;\n}\n",
        "export function App() {\n  return <div>hi there</div>;\n}\n",
        {("App", F, "formatting_only")},
    ),
    (
        "commonjs_function",
        "lib/util.cjs",
        "function f(a) {\n  return a;\n}\nmodule.exports = { f };\n",
        "function f(a) {\n  return a + 1;\n}\nmodule.exports = { f };\n",
        {("f", F, "modified_body")},
    ),
    (
        "mts_file",
        "lib/util.mts",
        "export const f = (a: number) => a;\n",
        "export const f = (a: number) => a + 1;\n",
        {("f", F, "modified_body")},
    ),
    (
        "path_alias_directory",
        "src/@app/core/~utils/util.ts",
        "export function slug(s: string) {\n  return s.trim();\n}\n",
        "export function slug(s: string) {\n  return s.trim().toLowerCase();\n}\n",
        {("slug", F, "modified_body")},
    ),
    (
        "unicode_identifier",
        "src/a.ts",
        "export function café(a: number) {\n  return a;\n}\n",
        "export function café(a: number) {\n  return a + 1;\n}\n",
        {("café", F, "modified_body")},
    ),
    (
        "function_removed",
        "src/a.ts",
        "export function f() {\n  return 1;\n}\nexport function g() {\n  return 2;\n}\n",
        "export function f() {\n  return 1;\n}\n",
        {("g", F, "removed")},
    ),
]


@pytest.mark.parametrize(
    ("case_id", "path", "base", "head", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_ecmascript_cases(
    case_id: str, path: str, base: str, head: str, expected: set[tuple[str, str, str]]
) -> None:
    result = run({path: base}, {path: head})
    assert set(summary(result)) == expected, case_id
    assert len(result.symbols) == len(expected)


def test_import_only_change_is_unattributed() -> None:
    result = run(
        {"src/a.ts": "import { a } from './a';\nexport const X = a;\n"},
        {"src/a.ts": "import { a, b } from './a';\nexport const X = a;\n"},
    )
    assert result.symbols == ()
    assert [u.reason for u in result.unattributed_hunks] == ["import"]


def test_rename_function_by_body_similarity() -> None:
    base = f"export function computeTotal(items: Item[]) {{\n{LONG}}}\n"
    head = base.replace("computeTotal", "orderTotal")
    result = run({"src/a.ts": base}, {"src/a.ts": head})
    assert summary(result) == [("orderTotal", F, "renamed")]


def test_move_function_between_ts_files() -> None:
    fn = f"export function helper(items: Item[]) {{\n{LONG}}}\n"
    result = run(
        {"src/a.ts": fn + "export const keep = 1;\n", "src/b.ts": "export const X = 1;\n"},
        {"src/a.ts": "export const keep = 1;\n", "src/b.ts": "export const X = 1;\n" + fn},
    )
    moved = [s for s in result.symbols if s.change_kind.value == "moved_between_files"]
    assert [(s.qualified_name, s.old_path, s.path) for s in moved] == [
        ("helper", "src/a.ts", "src/b.ts")
    ]


def test_language_and_ids() -> None:
    sym = run({"src/a.tsx": "export const x = () => 1;\n"}, {"src/a.tsx": "export const x = () => 2;\n"}).symbols[0]
    assert sym.language == "typescript"
    assert sym.symbol_id.startswith("typescript:src/a.tsx::x#function@")
    js = run({"a.js": "function f() {\n  return 1;\n}\n"}, {"a.js": "function f() {\n  return 2;\n}\n"}).symbols[0]
    assert js.language == "javascript"


@pytest.mark.parametrize("which", ["head", "base"])
def test_syntax_error_degrades_to_file_level(which: str) -> None:
    good = "export function f() {\n  return 1;\n}\n"
    bad = "export function f( {\n  return 1;\n}\n"
    base = bad if which == "base" else good
    head = bad.replace("1", "2") if which == "head" else good + "export const X = 1;\n"
    result = run({"src/a.ts": base}, {"src/a.ts": head})
    assert [(s.kind, s.change_kind.value) for s in result.symbols] == [("file", "modified_body")]
    assert any(n.startswith("parse_error_") for n in result.symbols[0].notes)


def test_crlf_typescript() -> None:
    base = "export function f() {\r\n  return 1;\r\n}\r\n"
    assert summary(run({"a.ts": base}, {"a.ts": base.replace("return 1", "return 2")})) == [
        ("f", F, "modified_body")
    ]
    converted = base.replace("\r\n", "\n")
    assert summary(run({"a.ts": base}, {"a.ts": converted})) == [("f", F, "formatting_only")]
