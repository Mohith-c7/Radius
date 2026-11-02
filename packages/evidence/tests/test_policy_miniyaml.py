"""VD-04: the strict YAML-subset parser used by policy.yml and waivers.yml."""

from __future__ import annotations

import pytest
from radius_evidence.policy import miniyaml
from radius_evidence.policy.globs import glob_problem, path_matches
from radius_evidence.policy.miniyaml import to_python

OK_CASES = [
    ("empty", "", None),
    ("comment only", "# nothing\n", None),
    ("scalar map", "a: 1\nb: x\nc: true\nd: null\ne: 0.5\n", {"a": 1, "b": "x", "c": True, "d": None, "e": 0.5}),
    ("nested map", "a:\n  b:\n    c: 2\n", {"a": {"b": {"c": 2}}}),
    ("flow list", "a: [x, 'y z', \"w\", 3]\n", {"a": ["x", "y z", "w", 3]}),
    ("empty flow list", "a: []\n", {"a": []}),
    ("block list", "a:\n  - x\n  - y\n", {"a": ["x", "y"]}),
    ("list at key indent", "a:\n- x\n- y\n", {"a": ["x", "y"]}),
    ("list of maps", "a:\n  - id: 1\n    n: x\n  - id: 2\n", {"a": [{"id": 1, "n": "x"}, {"id": 2}]}),
    ("quoted colon", 'a: "x: y"\n', {"a": "x: y"}),
    ("single quote escape", "a: 'it''s'\n", {"a": "it's"}),
    ("double quote escape", 'a: "l1\\nl2"\n', {"a": "l1\nl2"}),
    ("trailing comment", "a: 1  # note\n", {"a": 1}),
    ("hash inside quotes", 'a: "x # y"\n', {"a": "x # y"}),
    ("date stays text", "a: 2026-12-01\n", {"a": "2026-12-01"}),
    ("rule key with colon", "T012:check: low\n", {"T012:check": "low"}),
    ("document marker", "---\na: 1\n", {"a": 1}),
    ("crlf", "a: 1\r\nb: 2\r\n", {"a": 1, "b": 2}),
    ("bom", "\ufeffa: 1\n", {"a": 1}),
    ("null item", "a:\n  -\n  - x\n", {"a": [None, "x"]}),
    ("key without value", "a:\nb: 1\n", {"a": None, "b": 1}),
]


@pytest.mark.parametrize(("name", "text", "expected"), OK_CASES, ids=[c[0] for c in OK_CASES])
def test_parses(name: str, text: str, expected: object) -> None:
    result = miniyaml.parse(text)
    assert not result.fatal, [str(e) for e in result.errors]
    assert to_python(result.root) == expected


FATAL_CASES = [
    ("tab indent", "a:\n\tb: 1\n", 2, "Tabs"),
    ("anchor", "a: &x 1\n", 1, "anchors"),
    ("alias", "a: *x\n", 1, "aliases"),
    ("tag", "a: !!str 1\n", 1, "tags"),
    ("flow map", "a: {b: 1}\n", 1, "Flow mappings"),
    ("block scalar", "a: |\n  text\n", 1, "Block scalars"),
    ("folded scalar", "a: >\n  text\n", 1, "Block scalars"),
    ("unterminated quote", 'a: "x\n', 1, "Unterminated"),
    ("unterminated list", "a: [x, y\n", 1, "Expected ','"),
    ("unterminated list 2", "a: [x, y,\n", 1, "Unterminated"),
    ("bad escape", 'a: "\\q"\n', 1, "escape"),
    ("text after quote", "a: 'x' y\n", 1, "after quoted"),
    ("unquoted colon value", "a: b: c\n", 1, "Unquoted"),
    ("trailing colon value", "a: x:\n", 1, "Unquoted"),
    ("no colon", "just text\n", 1, "key: value"),
    ("bad key", "1a: x\n", 1, "key: value"),
    ("second document", "a: 1\n---\nb: 2\n", 2, "Multiple YAML"),
    ("nested seq", "a:\n  - - x\n", 2, "Nested sequences"),
    ("bad indent", "a: 1\n   b: 2\n", 2, "Unexpected indentation"),
    ("list empty item", "a: [x, , y]\n", 1, "Unsupported or empty"),
    ("list trailing text", "a: [x] y\n", 1, "after list"),
    ("merge-ish percent", "a: %x\n", 1, "indicator"),
    ("deep nesting", "".join("  " * i + f"k{i}:\n" for i in range(12)) + "  " * 12 + "v: 1\n", 9, "Nesting deeper"),
]


@pytest.mark.parametrize(("name", "text", "line", "needle"), FATAL_CASES, ids=[c[0] for c in FATAL_CASES])
def test_fatal_errors_carry_the_line(name: str, text: str, line: int, needle: str) -> None:
    result = miniyaml.parse(text)
    assert result.fatal and result.root is None
    diag = result.errors[-1]
    assert needle in diag.message, diag
    assert diag.line == line, diag
    assert str(diag).startswith(f"line {line}:")


def test_duplicate_key_is_an_error_but_not_fatal() -> None:
    result = miniyaml.parse("a: 1\na: 2\n")
    assert not result.fatal
    assert to_python(result.root) == {"a": 1}
    assert result.errors[0].line == 2 and "Duplicate" in result.errors[0].message


def test_size_limits_do_not_raise() -> None:
    big = "a: " + "x" * (miniyaml.MAX_BYTES + 1)
    assert miniyaml.parse(big).fatal
    many = "\n".join("a: 1" for _ in range(miniyaml.MAX_LINES + 1))
    assert miniyaml.parse(many).fatal
    assert miniyaml.parse(None).fatal  # type: ignore[arg-type]


def test_parser_is_linear_on_hostile_input() -> None:
    text = "a: [" + ",".join("x" for _ in range(5000)) + "]\n"
    assert not miniyaml.parse(text).fatal


@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        ("src/auth/**", "src/auth/a.py", True),
        ("src/auth/**", "src/auth/x/y/z.py", True),
        ("src/auth/**", "src/authx/a.py", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("**/x.py", "x.py", True),
        ("**/x.py", "a/b/x.py", True),
        ("**/x.py", "a/b/y.py", False),
        ("a?c.py", "abc.py", True),
        ("a?c.py", "a/c.py", False),
        ("./src/a.py", "src/a.py", True),
        ("src/a.py", ".\\src\\a.py", True),
        ("docs/**", "docs/", False),
    ],
)
def test_glob_matching(glob: str, path: str, expected: bool) -> None:
    assert path_matches(glob, path) is expected


@pytest.mark.parametrize(
    "glob",
    ["", "/etc/**", "C:/x", "../x", "a/../b", "a**b", "**a", "x" * 300, "a\x00b", "*" * 20],
)
def test_bad_globs_are_rejected_and_never_match(glob: str) -> None:
    assert glob_problem(glob) is not None
    assert path_matches(glob, "a") is False
