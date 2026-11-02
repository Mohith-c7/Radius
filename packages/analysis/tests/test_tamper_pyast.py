"""EV-02: unit tests for the assertion classifier and manifest parsers."""

from __future__ import annotations

import ast

import pytest
from radius_analysis.tamper import pyast
from radius_analysis.tamper.rules import dependencies as deps


def expr(text: str) -> ast.expr:
    return ast.parse(text, mode="eval").body


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("x == 1", "exact"),
        ("x is None", "exact"),
        ("x != None", "not_none"),
        ("x is not None", "not_none"),
        ("x != 3", "negative"),
        ("x not in y", "negative"),
        ("x in y", "membership"),
        ("x >= 1", "ordering"),
        ("0 < x < 3", "ordering"),
        ("x == pytest.approx(1.0)", "approx"),
        ("pytest.approx(1.0) == x", "approx"),
        ("isinstance(x, int)", "isinstance"),
        ("isinstance(x, object)", "tautology"),
        ("x", "truthy"),
        ("f(x)", "truthy"),
        ("not x", "truthy"),
        ("True", "tautology"),
        ("1", "tautology"),
        ("'text'", "tautology"),
        ("(1, 2)", "tautology"),
        ("not False", "tautology"),
        ("not None", "tautology"),
        ("x == x", "tautology"),
        ("x <= x", "tautology"),
        ("x or True", "tautology"),
        ("x and y == 2", "truthy"),
        ("x == 1 and y == 2", "exact"),
        ("x == 1 or y == 2", "ordering"),
        ("False", "truthy"),
    ],
)
def test_classify_expr(text: str, kind: str) -> None:
    assert pyast.classify_expr(expr(text)).kind == kind


def test_conjunct_counting_and_strength_order() -> None:
    a = pyast.classify_expr(expr("x == 1 and y == 2 and z == 3"))
    assert a.conjuncts == 3 and a.strength == pyast.STRENGTH["exact"]
    assert pyast.STRENGTH["exact"] > pyast.STRENGTH["membership"] > pyast.STRENGTH["not_none"]
    assert pyast.STRENGTH["tautology"] == 0


@pytest.mark.parametrize(
    ("call", "kind", "tolerance"),
    [
        ("self.assertEqual(a, 1)", "exact", None),
        ("self.assertEqual(a, a)", "tautology", None),
        ("self.assertEquals(a, 1)", "exact", None),
        ("self.assertIsNone(a)", "exact", None),
        ("self.assertIsNotNone(a)", "not_none", None),
        ("self.assertTrue(a == 1)", "exact", None),
        ("self.assertTrue(True)", "tautology", None),
        ("self.assertTrue()", "truthy", None),
        ("self.assertFalse(False)", "tautology", None),
        ("self.assertFalse(a)", "truthy", None),
        ("self.assertIn(a, b)", "membership", None),
        ("self.assertGreater(a, 1)", "ordering", None),
        ("self.assertNotEqual(a, 1)", "negative", None),
        ("self.assertIsInstance(a, int)", "isinstance", None),
        ("self.assertRaises(ValueError)", "raises", None),
        ("self.assertAlmostEqual(a, 1.0)", "approx", (0.0, 0.5e-7)),
        ("self.assertAlmostEqual(a, 1.0, places=2)", "approx", (0.0, 0.5e-2)),
        ("self.assertAlmostEqual(a, 1.0, 3)", "approx", (0.0, 0.5e-3)),
        ("self.assertAlmostEqual(a, 1.0, delta=0.1)", "approx", (0.0, 0.1)),
        ("mock.assert_called_once()", "mock_assert", None),
    ],
)
def test_unittest_and_mock_assertions(call: str, kind: str, tolerance: tuple | None) -> None:
    (found,) = pyast.extract_assertions(ast.parse(call))
    assert found.kind == kind
    if tolerance:
        assert found.tolerance == pytest.approx(tolerance)


def test_approx_parameters() -> None:
    def tol(src: str) -> tuple[float, float]:
        return pyast.classify_expr(expr(src)).tolerance

    assert tol("x == pytest.approx(1)") == (1e-6, 1e-12)
    assert tol("x == pytest.approx(1, rel=0.1)") == (0.1, 1e-12)
    assert tol("x == pytest.approx(1, abs=0.5)") == (0.0, 0.5)
    assert tol("x == pytest.approx(1, rel=-1e-3)")[0] == pytest.approx(-1e-3)


def test_raises_context_managers_and_noise() -> None:
    src = (
        "def test_a():\n"
        "    with pytest.raises(ValueError, match='x'):\n        f()\n"
        "    with pytest.raises(KeyError):\n        f()\n"
        "    with self.assertRaisesRegex(ValueError, 'x'):\n        f()\n"
        "    with open('f') as fh:\n        pass\n"
    )
    found = pyast.extract_assertions(ast.parse(src))
    assert [a.raises for a in found] == ["ValueError", "KeyError", "ValueError"]
    assert [a.op for a in found] == ["match", "nomatch", "match"]


def test_collect_tests_structure() -> None:
    src = (
        "import pytest\n"
        "pytestmark = pytest.mark.slow\n"
        "@pytest.mark.parametrize('a', [1, 2])\n"
        "def test_a(a):\n    assert f(a)\n"
        "class TestX:\n"
        "    def test_b(self):\n        assert g() == 1\n"
        "    def helper(self):\n        pass\n"
        "class Other(unittest.TestCase):\n"
        "    async def test_c(self):\n        pass\n"
        "class NotATest:\n    def test_d(self):\n        pass\n"
        "def helper():\n    pass\n"
    )
    mod = pyast.collect_tests(pyast.parse_python(src))
    assert sorted(mod.tests) == ["Other.test_c", "TestX.test_b", "test_a"]
    assert mod.module_marks == ("pytest.mark.slow",)
    assert mod.tests["test_a"].param_cases == ("'a'=1", "'a'=2")
    assert mod.tests["Other.test_c"].emptied and not mod.tests["TestX.test_b"].emptied
    assert mod.tests["TestX.test_b"].called == frozenset({"g"})
    assert mod.tests["test_a"].start == 3  # decorator line included


def test_literal_text_and_helpers() -> None:
    assert pyast.literal_text(expr("[1, 2]")) == "[1, 2]"
    assert pyast.literal_text(expr("-3")) == "-3"
    assert pyast.literal_text(expr("f(x)")) is None
    assert pyast.is_stub_body(ast.parse("pass\n...\n'doc'").body)
    assert not pyast.is_stub_body(ast.parse("x = 1").body)
    assert pyast.intersects(2, 4, {3}) and not pyast.intersects(2, 4, {9})
    assert pyast.intersects(1, 5000, {4000})


# ---------------------------------------------------------------- manifests


def test_parse_requirements() -> None:
    text = (
        "# comment\n-r base.txt\nRequests[security]>=2.0 ; python_version>'3'\n"
        "my_pkg==1.0\n./local\ngit+https://x/y.git\nflask\n"
    )
    assert deps.parse_requirements(text) == {
        "requests": ">=2.0", "my-pkg": "==1.0", "flask": "",
    }


def test_parse_pyproject_all_dependency_tables() -> None:
    text = (
        '[project]\nname="x"\ndependencies=["requests>=2", "Pydantic"]\n'
        '[project.optional-dependencies]\ndev=["pytest"]\n'
        '[dependency-groups]\nlint=["ruff"]\n'
        '[tool.poetry.dependencies]\npython="^3.12"\nhttpx="^0.27"\n'
        '[tool.poetry.group.test.dependencies]\nhypothesis="*"\n'
    )
    assert set(deps.parse_pyproject(text)) == {
        "requests", "pydantic", "pytest", "ruff", "httpx", "hypothesis",
    }
    assert deps.manifest_deps("sub/pyproject.toml", text) == deps.parse_pyproject(text)
    assert deps.manifest_deps("requirements.txt", "a\n") == {"a": ""}


def test_parse_lock_names() -> None:
    assert deps.parse_lock_names("uv.lock", '[[package]]\nname="Foo_Bar"\n') == {"foo-bar"}
    assert deps.parse_lock_names("Pipfile.lock", '{"default": {"A": {}}, "develop": {"b": {}}}') == {"a", "b"}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("requests", "requests", 0), ("requets", "requests", 1), ("abc", "xyz", 3),
     ("a", "abcdef", 3), ("flask", "flasks", 1)],
)
def test_edit_distance(a: str, b: str, expected: int) -> None:
    assert deps.edit_distance(a, b, limit=2) == min(expected, 3)


def test_dist_for_module_aliases() -> None:
    assert deps.dist_for_module("yaml") == "pyyaml"
    assert deps.dist_for_module("google.protobuf") == "protobuf"
    assert deps.dist_for_module("My_Pkg.sub") == "my-pkg"
    assert deps.normalize_name("A_b.C") == "a-b-c"
