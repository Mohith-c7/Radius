"""LK-01: table-driven Python symbol-change cases (one case per change kind / edge)."""

from __future__ import annotations

import pytest
from radius_analysis.symbol_changes.testing import dedent, run, summary

A = "pkg/a.py"
B = "pkg/b.py"

F = "function"
M = "method"
C = "class"

# (case id, base source, head source, expected {(qualified_name, kind, change_kind)})
CASES: list[tuple[str, str, str, set[tuple[str, str, str]]]] = [
    (
        "body_change",
        "def f():\n    return 1\n",
        "def f():\n    return 2\n",
        {("f", F, "modified_body")},
    ),
    (
        "signature_param_added",
        "def f(a):\n    return a\n",
        "def f(a, b):\n    return a\n",
        {("f", F, "modified_signature")},
    ),
    (
        "signature_default_changed",
        "def f(a=1):\n    return a\n",
        "def f(a=2):\n    return a\n",
        {("f", F, "modified_signature")},
    ),
    (
        "signature_return_annotation",
        "def f(a):\n    return a\n",
        "def f(a) -> int:\n    return a\n",
        {("f", F, "modified_signature")},
    ),
    (
        "signature_async_toggle",
        "def f(a):\n    return a\n",
        "async def f(a):\n    return a\n",
        {("f", F, "modified_signature")},
    ),
    (
        "decorator_added",
        "def f():\n    return 1\n",
        "@cache\ndef f():\n    return 1\n",
        {("f", F, "decorator_or_annotation_changed")},
    ),
    (
        "decorator_removed",
        "@cache\ndef f():\n    return 1\n",
        "def f():\n    return 1\n",
        {("f", F, "decorator_or_annotation_changed")},
    ),
    (
        "decorator_arguments_changed",
        "@pytest.mark.skipif(False, reason='x')\ndef test_a():\n    assert 1 == 1\n",
        "@pytest.mark.skipif(True, reason='x')\ndef test_a():\n    assert 1 == 1\n",
        {("test_a", F, "decorator_or_annotation_changed")},
    ),
    (
        "docstring_changed",
        'def f():\n    """old"""\n    return 1\n',
        'def f():\n    """new"""\n    return 1\n',
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "docstring_added",
        "def f():\n    return 1\n",
        'def f():\n    """Now documented."""\n    return 1\n',
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "comment_added_in_body",
        "def f():\n    x = 1\n    return x\n",
        "def f():\n    x = 1\n    # keep x\n    return x\n",
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "comment_changed_trailing",
        "def f():\n    return 1  # one\n",
        "def f():\n    return 1  # uno\n",
        {("f", F, "docstring_or_comment_only")},
    ),
    (
        "formatting_operator_spacing",
        "def f(a, b):\n    return a+b\n",
        "def f(a, b):\n    return a + b\n",
        {("f", F, "formatting_only")},
    ),
    (
        "formatting_quote_style",
        "def f():\n    return 'a'\n",
        'def f():\n    return "a"\n',
        {("f", F, "formatting_only")},
    ),
    (
        "formatting_blank_line_in_body",
        "def f():\n    x = 1\n    return x\n",
        "def f():\n    x = 1\n\n    return x\n",
        {("f", F, "formatting_only")},
    ),
    (
        "formatting_line_wrap",
        "def f(a, b):\n    return g(a, b)\n",
        "def f(a, b):\n    return g(\n        a,\n        b,\n    )\n",
        {("f", F, "formatting_only")},
    ),
    (
        "formatting_redundant_parens",
        "def f(a):\n    return a * 2\n",
        "def f(a):\n    return (a * 2)\n",
        {("f", F, "formatting_only")},
    ),
    (
        "added_function",
        "def f():\n    return 1\n",
        "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
        {("g", F, "added")},
    ),
    (
        "removed_function",
        "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
        "def f():\n    return 1\n",
        {("g", F, "removed")},
    ),
    (
        "added_class_with_methods",
        "X = 1\n",
        "X = 1\n\n\nclass K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n",
        {("K", C, "added"), ("K.a", M, "added"), ("K.b", M, "added")},
    ),
    (
        "removed_class_with_methods",
        "X = 1\n\n\nclass K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n",
        "X = 1\n",
        {("K", C, "removed"), ("K.a", M, "removed"), ("K.b", M, "removed")},
    ),
    (
        "method_added_to_existing_class",
        "class K:\n    def a(self):\n        return 1\n",
        "class K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n",
        {("K.b", M, "added")},
    ),
    (
        "method_body_changed_class_untouched",
        "class K:\n    x = 1\n\n    def a(self):\n        return 1\n",
        "class K:\n    x = 1\n\n    def a(self):\n        return 2\n",
        {("K.a", M, "modified_body")},
    ),
    (
        "class_attribute_changed",
        "class K:\n    x = 1\n\n    def a(self):\n        return 1\n",
        "class K:\n    x = 2\n\n    def a(self):\n        return 1\n",
        {("K", C, "modified_body")},
    ),
    (
        "class_base_changed",
        "class K(Base):\n    def a(self):\n        return 1\n",
        "class K(Other):\n    def a(self):\n        return 1\n",
        {("K", C, "modified_signature")},
    ),
    (
        "class_decorator_added",
        "class K:\n    x = 1\n",
        "@dataclass\nclass K:\n    x = 1\n",
        {("K", C, "decorator_or_annotation_changed")},
    ),
    (
        "nested_function_body_changed",
        "def outer():\n    def inner():\n        return 1\n    return inner\n",
        "def outer():\n    def inner():\n        return 2\n    return inner\n",
        {("outer.<locals>.inner", F, "modified_body")},
    ),
    (
        "nested_function_added",
        "def outer():\n    return 1\n",
        "def outer():\n    def inner():\n        return 2\n    return inner() + 1\n",
        {("outer", F, "modified_body"), ("outer.<locals>.inner", F, "added")},
    ),
    (
        "lambda_assignment_changed",
        "double = lambda x: x * 2\n",
        "double = lambda x: x * 3\n",
        {("double", "lambda", "modified_body")},
    ),
    (
        "lambda_assignment_added",
        "X = 1\n",
        "X = 1\nsquare = lambda x: x * x\n",
        {("square", "lambda", "added")},
    ),
    (
        "property_getter_changed",
        "class K:\n    @property\n    def v(self):\n        return 1\n",
        "class K:\n    @property\n    def v(self):\n        return 2\n",
        {("K.v", "property", "modified_body")},
    ),
    (
        "property_setter_added",
        "class K:\n    @property\n    def v(self):\n        return self._v\n",
        "class K:\n    @property\n    def v(self):\n        return self._v\n\n"
        "    @v.setter\n    def v(self, value):\n        self._v = value\n",
        {("K.v.setter", "property", "added")},
    ),
    (
        "async_method_body_changed",
        "class K:\n    async def a(self):\n        return await x()\n",
        "class K:\n    async def a(self):\n        return await y()\n",
        {("K.a", M, "modified_body")},
    ),
    (
        "dunder_init_changed",
        "class K:\n    def __init__(self):\n        self.a = 1\n",
        "class K:\n    def __init__(self):\n        self.a = 2\n",
        {("K.__init__", M, "modified_body")},
    ),
    (
        "def_inside_if_changed",
        "import sys\nif sys.platform == 'win32':\n    def f():\n        return 1\n",
        "import sys\nif sys.platform == 'win32':\n    def f():\n        return 2\n",
        {("f", F, "modified_body")},
    ),
    (
        "delete_single_line_in_body",
        "def f(a):\n    log(a)\n    return a\n",
        "def f(a):\n    return a\n",
        {("f", F, "modified_body")},
    ),
    (
        "module_statement_changed",
        "LIMIT = 10\n\n\ndef f():\n    return LIMIT\n",
        "LIMIT = 20\n\n\ndef f():\n    return LIMIT\n",
        {("<module>", "module", "modified_body")},
    ),
    (
        "module_docstring_changed",
        '"""Old."""\n\n\ndef f():\n    return 1\n',
        '"""New text."""\n\n\ndef f():\n    return 1\n',
        {("<module>", "module", "docstring_or_comment_only")},
    ),
    (
        "unicode_identifiers",
        "def cafe_cost(prix):\n    return prix\n\n\ndef \u53d8\u91cf(x):\n    return x\n",
        "def cafe_cost(prix):\n    return prix\n\n\ndef \u53d8\u91cf(x):\n    return x + 1\n",
        {("\u53d8\u91cf", F, "modified_body")},
    ),
    (
        "unicode_string_literal_changed",
        "def f():\n    return 'caf\u00e9'\n",
        "def f():\n    return 'cafe'\n",
        {("f", F, "modified_body")},
    ),
    (
        "reorder_methods_moves_one_block",
        "class K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n",
        "class K:\n    def b(self):\n        return 2\n\n    def a(self):\n        return 1\n",
        {("K.b", M, "formatting_only")},  # the diff moves one block; the other is context
    ),
]

LONG_BODY = (
    "    total = 0\n"
    "    for item in items:\n"
    "        if item.active and item.price > 0:\n"
    "            total += item.price * item.qty\n"
    "    return round(total, 2)\n"
)


@pytest.mark.parametrize(("case_id", "base", "head", "expected"), CASES, ids=[c[0] for c in CASES])
def test_python_cases(case_id: str, base: str, head: str, expected: set[tuple[str, str, str]]) -> None:
    result = run({A: base}, {A: head})
    assert set(summary(result)) == expected, case_id
    assert len(result.symbols) == len(expected)  # no duplicates


def test_rename_function_detected_by_body_similarity() -> None:
    base = f"def compute_total(items):\n{LONG_BODY}"
    head = f"def order_total(items):\n{LONG_BODY}"
    result = run({A: base}, {A: head})
    assert summary(result) == [("order_total", F, "renamed")]
    sym = result.symbols[0]
    assert sym.old_qualified_name == "compute_total"
    assert sym.confidence == 1.0
    assert sym.old_symbol_id != sym.new_symbol_id


def test_rename_method_keeps_class_untouched() -> None:
    base = f"class K:\n    def compute_total(self, items):\n{LONG_BODY.replace('    ', '        ', 1)}"
    base = "class K:\n    def compute_total(self, items):\n" + "".join(
        "    " + line + "\n" for line in LONG_BODY.splitlines()
    )
    head = base.replace("compute_total", "order_total")
    result = run({A: base}, {A: head})
    assert summary(result) == [("K.order_total", M, "renamed")]


def test_rename_with_body_change_has_secondary_kind_and_lower_confidence() -> None:
    base = f"def compute_total(items):\n{LONG_BODY}"
    head = f"def order_total(items):\n{LONG_BODY.replace('round(total, 2)', 'round(total, 3)')}"
    sym = run({A: base}, {A: head}).symbols[0]
    assert sym.change_kind.value == "renamed"
    assert [k.value for k in sym.secondary_kinds] == ["modified_body"]
    assert "renamed_with_body_changes" in sym.notes
    assert 0.85 <= sym.confidence < 1.0


def test_tiny_function_rename_is_not_guessed() -> None:
    result = run({A: "def a():\n    return 1\n"}, {A: "def b():\n    return 1\n"})
    assert set(summary(result)) == {("a", F, "removed"), ("b", F, "added")}


def test_move_method_between_classes_in_file() -> None:
    method = "".join("    " + line + "\n" for line in LONG_BODY.splitlines())
    base = f"class A:\n    def work(self, items):\n{method}\n\nclass B:\n    x = 1\n"
    head = f"class A:\n    x = 0\n\n\nclass B:\n    x = 1\n\n    def work(self, items):\n{method}"
    result = run({A: base}, {A: head})
    kinds = {(s.qualified_name, s.change_kind.value) for s in result.symbols}
    assert ("B.work", "moved") in kinds
    moved = next(s for s in result.symbols if s.change_kind.value == "moved")
    assert moved.old_qualified_name == "A.work"


def test_move_function_between_files() -> None:
    body = f"def helper(items):\n{LONG_BODY}"
    result = run(
        {A: body + "\n\ndef keep():\n    return 1\n", B: "X = 1\n"},
        {A: "def keep():\n    return 1\n", B: "X = 1\n\n\n" + body},
    )
    moved = [s for s in result.symbols if s.change_kind.value == "moved_between_files"]
    assert len(moved) == 1
    assert moved[0].path == B
    assert moved[0].old_path == A
    assert moved[0].qualified_name == "helper"
    assert {s.change_kind.value for s in result.symbols} == {"moved_between_files"}


def test_move_class_with_methods_between_files() -> None:
    method = "".join("    " + line + "\n" for line in LONG_BODY.splitlines())
    cls = f"class Repo:\n    def total(self, items):\n{method}\n    def other(self, items):\n{method}"
    result = run({A: cls, B: "X = 1\n"}, {A: "Y = 2\n", B: "X = 1\n\n\n" + cls})
    moved = {s.qualified_name for s in result.symbols if s.change_kind.value == "moved_between_files"}
    assert moved == {"Repo", "Repo.total", "Repo.other"}


def test_pure_file_rename_moves_every_symbol() -> None:
    src = "def f():\n    return 1\n\n\nclass K:\n    def m(self):\n        return 2\n"
    result = run({A: src}, {B: src}, renames={A: B})
    assert {(s.qualified_name, s.change_kind.value) for s in result.symbols} == {
        ("f", "moved_between_files"),
        ("K", "moved_between_files"),
        ("K.m", "moved_between_files"),
    }
    assert all(s.old_path == A and s.path == B for s in result.symbols)
    assert result.files[0].status.value == "renamed"


def test_file_rename_with_edit_keeps_secondary_kind() -> None:
    result = run(
        {A: "def f():\n    return 1\n"},
        {B: "def f():\n    return 2\n"},
        renames={A: B},
    )
    sym = result.symbols[0]
    assert sym.change_kind.value == "moved_between_files"
    assert [k.value for k in sym.secondary_kinds] == ["modified_body"]
    assert sym.hunks


def test_decorator_and_body_change_reports_body_with_decorator_secondary() -> None:
    result = run(
        {A: "@a\ndef f():\n    return 1\n"}, {A: "@b\ndef f():\n    return 2\n"}
    )
    sym = result.symbols[0]
    assert sym.change_kind.value == "modified_body"
    assert [k.value for k in sym.secondary_kinds] == ["decorator_or_annotation_changed"]


def test_overloads_are_disambiguated_and_stable() -> None:
    base = dedent(
        """
        from typing import overload

        @overload
        def f(a: int) -> int: ...
        @overload
        def f(a: str) -> str: ...
        def f(a):
            return a
        """
    )
    head = base.replace("return a", "return a * 2")
    result = run({A: base}, {A: head})
    assert summary(result) == [("f@3", F, "modified_body")]
    names = {s.qualified_name for s in run({A: base}, {A: base + "\n\ndef g():\n    return 1\n"}).symbols}
    assert names == {"g"}


def test_hunks_and_ranges_are_recorded() -> None:
    base = "def f(a):\n    x = 1\n    y = 2\n    z = 3\n    return a\n"
    head = "def f(a):\n    x = 10\n    y = 2\n    z = 30\n    return a\n"
    sym = run({A: base}, {A: head}, context=0).symbols[0]
    assert (sym.old_range.start, sym.old_range.end) == (1, 5)
    assert len(sym.hunks) == 2
    assert [(r.start, r.end) for r in sym.hunks[0].new_lines] == [(2, 2)]
    assert [(r.start, r.end) for r in sym.hunks[1].old_lines] == [(4, 4)]
    assert sym.old_signature == "def f(a)"
    assert sym.symbol_id.startswith("python:pkg/a.py::f#function@")
    assert sym.symbol_id == sym.new_symbol_id == sym.old_symbol_id


def test_signature_hash_changes_id_but_key_is_stable() -> None:
    result = run({A: "def f(a):\n    return a\n"}, {A: "def f(a, b):\n    return a\n"})
    sym = result.symbols[0]
    assert sym.old_symbol_id != sym.new_symbol_id
    assert sym.key == "python:pkg/a.py::f#function"


def test_import_only_change_is_unattributed() -> None:
    result = run({A: "import os\n\nX = 1\n"}, {A: "import os\nimport sys\n\nX = 1\n"})
    assert result.symbols == ()
    assert [u.reason for u in result.unattributed_hunks] == ["import"]


def test_module_level_comment_is_unattributed() -> None:
    result = run({A: "X = 1\n"}, {A: "# note\nX = 1\n"})
    assert result.symbols == ()
    assert [u.reason for u in result.unattributed_hunks] == ["blank_or_comment"]


def test_module_pseudo_symbol_can_be_disabled() -> None:
    from radius_analysis.symbol_changes import ExtractionOptions

    result = run(
        {A: "X = 1\n"}, {A: "X = 2\n"}, options=ExtractionOptions(module_pseudo_symbol=False)
    )
    assert result.symbols == ()
    assert [u.reason for u in result.unattributed_hunks] == ["module_level"]


def test_blank_line_between_members_is_unattributed() -> None:
    base = "class K:\n    def a(self):\n        return 1\n    def b(self):\n        return 2\n"
    head = "class K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n"
    result = run({A: base}, {A: head})
    assert result.symbols == ()
    assert [u.reason for u in result.unattributed_hunks] == ["blank_between_members"]


def test_suppression_marker_note() -> None:
    result = run(
        {A: "def f():\n    return g()\n"}, {A: "def f():\n    return g()  # type: ignore\n"}
    )
    sym = result.symbols[0]
    assert sym.change_kind.value == "docstring_or_comment_only"
    assert "suppression_marker_changed" in sym.notes
    assert not sym.is_behavioral


@pytest.mark.parametrize("which", ["head", "base", "both"])
def test_syntax_errors_degrade_to_file_level(which: str) -> None:
    good = "def f():\n    return 1\n"
    bad = "def f(:\n    return 1\n"
    base = bad if which in {"base", "both"} else good
    head = bad.replace("1", "2") if which in {"head", "both"} else good + "\nX = 1\n"
    result = run({A: base}, {A: head})
    assert len(result.symbols) == 1
    sym = result.symbols[0]
    assert (sym.kind, sym.qualified_name) == ("file", "<file>")
    assert sym.change_kind.value == "modified_body"
    assert any(n.startswith("parse_error_") for n in sym.notes)
    assert sym.confidence < 1.0
    assert result.files[0].level.value == "file"


def test_added_file_with_syntax_error_is_file_level_added() -> None:
    result = run({}, {A: "def (:\n"})
    assert summary(result) == [("<file>", "file", "added")]
    assert result.symbols[0].new_range is not None


def test_crlf_edit_and_line_ending_conversion() -> None:
    base = "def f():\r\n    return 1\r\n\r\n\r\ndef g():\r\n    return 2\r\n"
    head = base.replace("return 1", "return 3")
    assert summary(run({A: base}, {A: head})) == [("f", F, "modified_body")]
    converted = base.replace("\r\n", "\n")
    result = run({A: base}, {A: converted})
    assert {k for _n, _t, k in summary(result)} == {"formatting_only"}
    assert {n for n, _t, _k in summary(result)} == {"f", "g"}


def test_missing_newline_at_eof() -> None:
    diff = (
        "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n"
        "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n\\ No newline at end of file\n"
        "+    return 2\n\\ No newline at end of file\n"
    )
    result = run({A: "def f():\n    return 1"}, {A: "def f():\n    return 2"}, diff=diff)
    assert summary(result) == [("f", F, "modified_body")]


def test_utf8_bom_is_ignored() -> None:
    base = "\ufeffdef f():\n    return 1\n"
    head = "\ufeffdef f():\n    return 2\n"
    assert summary(run({A: base}, {A: head})) == [("f", F, "modified_body")]


def test_added_file_reports_all_symbols_added() -> None:
    result = run({}, {A: "import os\n\nX = 1\n\n\ndef f():\n    return 1\n"})
    assert {(n, k) for n, _t, k in summary(result)} == {("<module>", "added"), ("f", "added")}
    assert {u.reason for u in result.unattributed_hunks} == {"import", "blank_or_comment"}


def test_deleted_file_reports_all_symbols_removed() -> None:
    result = run({A: "def f():\n    return 1\n\n\nclass K:\n    pass\n"}, {})
    assert {(n, k) for n, _t, k in summary(result)} == {("f", "removed"), ("K", "removed")}
