"""LK-04: Python assertion extraction, table-driven (positive, negative, near-miss)."""

from __future__ import annotations

import textwrap
from typing import Any

import pytest
from radius_testing.assertions import AssertionRecord, extract_assertions

PRE = "import math\nimport pytest\nimport unittest\nfrom unittest import mock\nfrom pkg.mod import f, g\n\n"
FULL = "#!full\n"


def E(kind: str, cmp: str | None = None, **feat: Any) -> tuple[str, str | None, dict[str, Any]]:  # noqa: N802
    return (kind, cmp, feat)


def build(code: str) -> str:
    if code.startswith(FULL):
        return PRE + textwrap.dedent(code[len(FULL):])
    return PRE + "def test_t():\n" + textwrap.indent(textwrap.dedent(code).strip("\n"), "    ") + "\n"


def run(code: str, path: str = "tests/test_t.py") -> list[AssertionRecord]:
    return list(extract_assertions([path], {path: build(code)}).assertions)


def attr(rec: AssertionRecord, key: str) -> Any:
    sf = rec.strength_features
    if hasattr(sf, key):
        return getattr(sf, key)
    special = {
        "subject": rec.subject_text,
        "expected": rec.expected.text,
        "ec": rec.expected.complexity,
        "form": rec.expected.form,
        "lit": rec.expected.literal_kind,
        "framework": rec.framework,
        "conf": rec.confidence,
        "via": rec.via,
        "refs": {r.qualified for r in rec.subject_refs},
        "line": rec.location.line - PRE.count("\n") - 1,
    }
    return special[key]


def matches(rec: AssertionRecord, exp: tuple[str, str | None, dict[str, Any]]) -> bool:
    kind, cmp, feat = exp
    if rec.kind != kind or (cmp is not None and rec.comparator != cmp):
        return False
    return all(attr(rec, k) == v for k, v in feat.items())


def check(code: str, expects: list[tuple[str, str | None, dict[str, Any]]], path: str = "tests/test_t.py") -> None:
    records = run(code, path)
    remaining = list(records)
    for exp in expects:
        hit = next((r for r in remaining if matches(r, exp)), None)
        assert hit is not None, f"no record matches {exp}; got " + "; ".join(
            f"{r.kind.value}/{r.comparator}/{r.subject_text}|{r.expected.text}" for r in records
        )
        remaining.remove(hit)
    assert not remaining, "unexpected extra records: " + "; ".join(
        f"{r.kind.value}/{r.comparator}/{r.subject_text}" for r in remaining
    )


# --------------------------------------------------------------------------- pytest assert statements

ASSERT_CASES: list[tuple[str, str, list]] = [
    ("eq_literal", "assert f(1) == 3", [E("equality", "==", exactness="exact", ec=2, subject="f(1)", expected="3", refs={"pkg.mod.f"})]),
    ("eq_trivial_literal", "assert f(1) == 0", [E("equality", "==", ec=1)]),
    ("eq_swapped_literal_left", "assert 3 == f(1)", [E("equality", "==", subject="f(1)", expected="3")]),
    ("neq", "assert f(1) != 2", [E("equality", "!=", negated=True)]),
    ("eq_string", 'assert f(1) == "abc"', [E("equality", "==", ec=2, lit="str")]),
    ("eq_empty_string", 'assert f(1) == ""', [E("equality", "==", ec=1)]),
    ("eq_long_string", 'assert f(1) == "abcdefghijklmnopqrstuvwxyz0123"', [E("equality", "==", ec=3)]),
    ("eq_list_rich", "assert f(1) == [1, 2, 3]", [E("equality", "==", ec=3, lit="collection")]),
    ("eq_dict_small", 'assert f(1) == {"a": 1}', [E("equality", "==", ec=2)]),
    ("eq_nested", "assert f(1) == [[1], [2]]", [E("equality", "==", ec=3)]),
    ("eq_bool", "assert f(1) == True", [E("equality", "==", ec=1, lit="bool")]),
    ("eq_negative_number", "assert f(1) == -5", [E("equality", "==", ec=2)]),
    ("eq_expression", "assert f(1) == g(2) + 1", [E("equality", "==", form="expression", ec=0)]),
    ("eq_via_local_literal", "expected = [1, 2, 3]\nassert f(1) == expected", [E("equality", "==", form="literal", ec=3)]),
    ("eq_local_nonliteral", "expected = g(1)\nassert f(1) == expected", [E("equality", "==", form="expression")]),
    ("truthy", "assert f(1)", [E("truthiness", "truthy", exactness="truthiness", negated=False)]),
    ("not_truthy", "assert not f(1)", [E("truthiness", "truthy", negated=True)]),
    ("is_none", "assert f(1) is None", [E("none_check", "is", exactness="none_only", negated=False)]),
    ("is_not_none", "assert f(1) is not None", [E("none_check", "is not", negated=True)]),
    ("eq_none", "assert f(1) == None", [E("none_check", "==")]),
    ("is_true", "assert f(1) is True", [E("identity", "is", exactness="identity")]),
    ("is_other", "x = g(1)\nassert f(1) is x", [E("identity", "is")]),
    ("in_literal_member", 'assert "a" in f(1)', [E("membership", "in", subject="f(1)", expected="'a'", ec=2)]),
    ("in_tuple", "assert f(1) in (1, 2)", [E("membership", "in", subject="f(1)", ec=2)]),
    ("not_in", "assert f(1) not in [1]", [E("membership", "not in", negated=True)]),
    ("isinstance_ok", "assert isinstance(f(1), int)", [E("type_check", "isinstance", exactness="type_only", subject="f(1)")]),
    ("isinstance_tuple", "assert isinstance(f(1), (int, str))", [E("type_check")]),
    ("isinstance_object_dead", "assert isinstance(f(1), object)", [E("type_check", dead=True, dead_reason="tautology")]),
    ("issubclass", "assert issubclass(f(1), Exception)", [E("type_check", "issubclass")]),
    ("len_eq", "assert len(f(1)) == 3", [E("length", "==", exactness="length_only", subject="f(1)")]),
    ("len_gt", "assert len(f(1)) > 0", [E("length", ">")]),
    ("len_truthy", "assert len(f(1))", [E("length", "truthy")]),
    ("len_swapped", "assert 3 == len(f(1))", [E("length", "==", subject="f(1)")]),
    ("gt", "assert f(1) > 0", [E("comparison", ">", exactness="ordering")]),
    ("le", "assert f(1) <= 10", [E("comparison", "<=")]),
    ("chain", "assert 0 < f(1) < 10", [E("comparison", "chain < <", exactness="ordering")]),
    ("chain_eq", "assert f(1) == g(1) == 3", [E("equality", "chain == ==", exactness="exact")]),
    ("all_gen", "assert all(x > 0 for x in f(1))", [E("quantified", "all:>", quantifier="all", exactness="ordering")]),
    ("any_gen", "assert any(x == 3 for x in f(1))", [E("quantified", "any:==", quantifier="any", exactness="exact")]),
    ("all_plain", "assert all(f(1))", [E("quantified", "all", exactness="truthiness")]),
    ("all_listcomp", "assert all([x is not None for x in f(1)])", [E("quantified", quantifier="all", negated=True)]),
    ("and_two", "assert f(1) == 3 and g(1) is None", [E("equality", "=="), E("none_check", "is")]),
    ("and_same_kind_distinct", "assert f(1) == 1 and f(1) == 2", [E("equality", "==", expected="1"), E("equality", "==", expected="2")]),
    ("or_disjunction", "assert f(1) == 3 or g(1) == 4", [E("disjunction", "or", exactness="disjunction", dead=False)]),
    ("or_true_dead", "assert f(1) or True", [E("disjunction", dead=True, dead_reason="tautology")]),
    ("approx_default", "assert f(1) == pytest.approx(0.3)", [E("approx", "==", tolerance_rel=1e-6, tolerance_abs=1e-12, expected="0.3")]),
    ("approx_rel", "assert f(1) == pytest.approx(0.3, rel=0.1)", [E("approx", tolerance_rel=0.1, tolerance_abs=None)]),
    ("approx_abs", "assert f(1) == pytest.approx(1, abs=0.5)", [E("approx", tolerance_abs=0.5, tolerance_rel=None)]),
    ("approx_swapped", "assert pytest.approx(0.3) == f(1)", [E("approx", subject="f(1)")]),
    ("isclose", "assert math.isclose(f(1), 0.3)", [E("approx", "isclose", tolerance_rel=1e-9, tolerance_abs=0.0)]),
    ("isclose_tol", "assert math.isclose(f(1), 0.3, rel_tol=1e-3, abs_tol=0.01)", [E("approx", tolerance_rel=1e-3, tolerance_abs=0.01)]),
    ("regex_match", 'import re\nassert re.match("a+", f(1))', [E("regex", "match", exactness="pattern", subject="f(1)", form="pattern")]),
    ("not_regex_like", "assert f(1).startswith('a')", [E("truthiness")]),
    ("assert_with_message", 'assert f(1) == 3, "bad value"', [E("equality", "==", ec=2)]),
    ("walrus", "assert (r := f(1)) == 3", [E("equality", "==")]),
    ("not_eq", "assert not f(1) == 3", [E("equality", "==", negated=True)]),
    ("not_not", "assert not not f(1)", [E("truthiness", negated=False)]),
    ("attr_ref", "import pkg.mod as pm\nassert pm.LIMIT == 3", [E("equality", "==", refs={"pkg.mod.LIMIT"})]),
    ("method_on_instance", "from pkg.mod import Calc\nc = Calc()\nassert c.add(1) == 2", [E("equality", "==", refs={"pkg.mod.Calc.add", "pkg.mod.Calc"})]),
    ("dataflow_ref", "r = f(1)\nassert r == 3", [E("equality", "==", subject="r", refs={"pkg.mod.f"}, distinct_subject_symbols=1)]),
    ("two_symbols", "assert f(1) + g(2) == 3", [E("equality", "==", distinct_subject_symbols=2)]),
    ("stdlib_not_symbol", "import json\nassert json.loads(f(1)) == 3", [E("equality", "==", refs={"pkg.mod.f"}, distinct_subject_symbols=1)]),
    ("builtin_not_symbol", "assert sorted(f(1)) == [1, 2]", [E("equality", "==", refs={"pkg.mod.f"})]),
    ("local_unimported_call_ignored", "assert helper_missing(1) == 2", [E("equality", "==", refs=set(), distinct_subject_symbols=0)]),
]

DEAD_CASES: list[tuple[str, str, list]] = [
    ("true", "assert True", [E("truthiness", "constant", dead=True, dead_reason="constant_true", exactness="none")]),
    ("one", "assert 1", [E("truthiness", dead=True, dead_reason="constant_true")]),
    ("string", 'assert "ok"', [E("truthiness", dead=True, dead_reason="constant_true")]),
    ("false", "assert False", [E("truthiness", dead=True, dead_reason="constant_false")]),
    ("zero", "assert 0", [E("truthiness", dead=True, dead_reason="constant_false")]),
    ("not_false", "assert not False", [E("truthiness", dead=True, dead_reason="constant_true")]),
    ("tuple", 'assert (f(1) == 2, "msg")', [E("truthiness", dead=True, dead_reason="constant_true")]),
    ("fstring", 'assert f"{f(1)}"', [E("truthiness", dead=True)]),
    ("literal_cmp", "assert 1 == 1", [E("equality", dead=True, dead_reason="literal_comparison")]),
    ("literal_cmp_str", 'assert "a" != "b"', [E("equality", dead=True, dead_reason="literal_comparison")]),
    ("tautology_name", "x = f(1)\nassert x == x", [E("equality", dead=True, dead_reason="tautology")]),
    ("tautology_attr", "x = f(1)\nassert x.a is x.a", [E("identity", dead=True, dead_reason="tautology")]),
    ("not_dead_call_both", "assert f(1) == f(1)", [E("equality", dead=False, circular=True)]),
    ("not_dead_normal", "assert f(1) == 1", [E("equality", dead=False)]),
    ("empty_tuple_not_dead", "assert ()", [E("truthiness", dead=False)]),
    ("unittest_true", FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        self.assertTrue(True)", [E("truthiness", dead=True)]),
]

RAISES_CASES: list[tuple[str, str, list]] = [
    ("specific", "with pytest.raises(ValueError):\n    f(None)", [E("exception", "raises", exception_specificity="specific", exception_match=False, exception_block_size=1, subject="f(None)", refs={"pkg.mod.f"})]),
    ("specific_match", 'with pytest.raises(ValueError, match="bad"):\n    f(None)', [E("exception", exception_specificity="specific_match", exception_match=True)]),
    ("broad", "with pytest.raises(Exception):\n    f(None)", [E("exception", exception_specificity="broad", ec=1)]),
    ("base_exception", "with pytest.raises(BaseException):\n    f(None)", [E("exception", exception_specificity="broad")]),
    ("broad_with_match", 'with pytest.raises(Exception, match="x"):\n    f(None)', [E("exception", exception_specificity="broad", exception_match=True)]),
    ("tuple_specific", "with pytest.raises((ValueError, TypeError)):\n    f(None)", [E("exception", exception_specificity="specific")]),
    ("tuple_broad", "with pytest.raises((Exception, BaseException)):\n    f(None)", [E("exception", exception_specificity="broad")]),
    ("dotted_exc", "import pkg\nwith pytest.raises(pkg.mod.MyError):\n    f(None)", [E("exception", exception_specificity="specific", ec=2)]),
    ("block_two_statements", "with pytest.raises(ValueError):\n    x = g(1)\n    f(x)", [E("exception", exception_block_size=2)]),
    ("inspected", 'with pytest.raises(ValueError) as ei:\n    f(None)\nassert str(ei.value) == "bad"', [E("exception", exception_inspected=True), E("equality", "==")]),
    ("not_inspected", "with pytest.raises(ValueError) as ei:\n    f(None)", [E("exception", exception_inspected=False)]),
    ("call_form", "pytest.raises(ValueError, f, None)", [E("exception", "raises", subject="f", refs={"pkg.mod.f"})]),
    ("warns", 'with pytest.warns(UserWarning):\n    f(1)', [E("warning", "warns", exception_specificity="specific")]),
    ("warns_match", 'with pytest.warns(UserWarning, match="w"):\n    f(1)', [E("warning", exception_specificity="specific_match")]),
    ("deprecated_call", "with pytest.deprecated_call():\n    f(1)", [E("warning")]),
    ("raises_nested_assert", "with pytest.raises(KeyError):\n    assert f(1) == 2", [E("exception"), E("equality")]),
    ("unittest_ctx", FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        with self.assertRaises(ValueError):\n            f(1)", [E("exception", framework="unittest", exception_specificity="specific")]),
    ("unittest_regex", FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        with self.assertRaisesRegex(ValueError, 'x'):\n            f(1)", [E("exception", exception_specificity="specific_match", exception_match=True)]),
    ("unittest_call", FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        self.assertRaises(ValueError, f, 1)", [E("exception", subject="f")]),
    ("unittest_warns", FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        with self.assertWarns(UserWarning):\n            f(1)", [E("warning")]),
    ("raises_no_type", "with pytest.raises():\n    f(1)", [E("exception", exception_specificity="none")]),
    ("not_pytest_raises", "from other import raises\nwith raises(ValueError):\n    f(1)", []),
]

UNITTEST_BODY = FULL + "class T(unittest.TestCase):\n    def test_t(self):\n        {}"
UNITTEST_CASES: list[tuple[str, str, list]] = [
    ("equal", "self.assertEqual(f(1), 3)", [E("equality", "==", subject="f(1)", expected="3", framework="unittest")]),
    ("equal_swapped", "self.assertEqual(3, f(1))", [E("equality", subject="f(1)")]),
    ("not_equal", "self.assertNotEqual(f(1), 3)", [E("equality", "!=", negated=True)]),
    ("list_equal", "self.assertListEqual(f(1), [1])", [E("equality", "==")]),
    ("dict_equal", "self.assertDictEqual(f(1), {})", [E("equality", ec=1)]),
    ("count_equal", "self.assertCountEqual(f(1), [1, 2])", [E("equality", "count_equal")]),
    ("true", "self.assertTrue(f(1))", [E("truthiness", "truthy", subject="f(1)")]),
    ("false", "self.assertFalse(f(1))", [E("truthiness", "falsy", negated=True)]),
    ("is", "self.assertIs(f(1), g(1))", [E("identity", "is")]),
    ("is_not", "self.assertIsNot(f(1), g(1))", [E("identity", "is not", negated=True)]),
    ("is_none", "self.assertIsNone(f(1))", [E("none_check", "is None", exactness="none_only")]),
    ("is_not_none", "self.assertIsNotNone(f(1))", [E("none_check", "is not None", negated=True)]),
    ("in", 'self.assertIn("a", f(1))', [E("membership", "in", subject="f(1)", expected="'a'")]),
    ("not_in", 'self.assertNotIn("a", f(1))', [E("membership", "not in", negated=True)]),
    ("isinstance", "self.assertIsInstance(f(1), int)", [E("type_check", "isinstance")]),
    ("not_isinstance", "self.assertNotIsInstance(f(1), int)", [E("type_check", "not isinstance", negated=True)]),
    ("greater", "self.assertGreater(f(1), 0)", [E("comparison", ">")]),
    ("less_equal", "self.assertLessEqual(f(1), 9)", [E("comparison", "<=")]),
    ("almost_default", "self.assertAlmostEqual(f(1), 0.3)", [E("approx", "almost_equal", tolerance_abs=0.5e-7)]),
    ("almost_places", "self.assertAlmostEqual(f(1), 0.3, places=2)", [E("approx", tolerance_abs=0.005)]),
    ("almost_delta", "self.assertAlmostEqual(f(1), 0.3, delta=0.1)", [E("approx", tolerance_abs=0.1)]),
    ("not_almost", "self.assertNotAlmostEqual(f(1), 0.3)", [E("approx", "not_almost_equal", negated=True)]),
    ("regex", 'self.assertRegex(f(1), "a+")', [E("regex", "regex", exactness="pattern")]),
    ("unknown_helper", "self.assert_valid(f(1))", [E("unknown_assert", "assert_valid", conf=0.4)]),
    ("fail_is_not_an_assertion", 'self.fail("x")', []),
    ("custom_but_not_assert", "self.helper_value(f(1))", []),
]

MOCK_CASES: list[tuple[str, str, list]] = [
    ("created_only", "m = mock.Mock()\nm()\nm.assert_called_once()", [E("mock_call", "assert_called_once", mock_only=True, mock_origin="created", exactness="call_only", framework="mock")]),
    ("created_magic_with_args", "m = mock.MagicMock()\nm.foo(1)\nm.foo.assert_called_with(1)", [E("mock_call", "assert_called_with", mock_only=True, exactness="call_args", ec=1)]),
    ("created_not_called", "m = mock.Mock()\nm.assert_not_called()", [E("mock_call", "assert_not_called", mock_only=True)]),
    ("escaped_arg", "m = mock.Mock()\nf(m)\nm.assert_called_once_with(1)", [E("mock_call", mock_only=False, mock_origin="created")]),
    ("escaped_kw", "m = mock.Mock()\nf(cb=m)\nm.assert_called_once()", [E("mock_call", mock_only=False)]),
    ("escaped_alias", "m = mock.Mock()\nobj = m\nobj.assert_called()", [E("mock_call", mock_only=False)]),
    ("escaped_in_dict", 'm = mock.Mock()\nf({"k": m})\nm.assert_called()', [E("mock_call", mock_only=False)]),
    ("patched_ctx", 'with mock.patch("pkg.mod.g") as mg:\n    f(1)\n    mg.assert_called_once()', [E("mock_call", mock_only=False, mock_origin="patched")]),
    ("patched_assign", 'mg = mock.patch("pkg.mod.g")\nf(1)\nmg.assert_called_once()', [E("mock_call", mock_only=False, mock_origin="patched")]),
    ("patch_object", 'with mock.patch.object(g, "x") as mg:\n    f(1)\nmg.assert_called()', [E("mock_call", mock_only=False, mock_origin="patched")]),
    ("decorator_patch", FULL + 'class_ = 1\n@mock.patch("pkg.mod.g")\ndef test_t(mg):\n    f(1)\n    mg.assert_called_once_with(1)', [E("mock_call", mock_only=False, mock_origin="patched")]),
    ("mocker_patch", FULL + 'def test_t(mocker):\n    mg = mocker.patch("pkg.mod.g")\n    f(1)\n    mg.assert_called_once()', [E("mock_call", mock_only=False, mock_origin="patched")]),
    ("any_args", "m = mock.Mock()\nm(1)\nm.assert_called_with(mock.ANY)", [E("mock_call", ec=0, mock_only=True)]),
    ("any_calls", "m = mock.Mock()\nm.assert_has_calls([mock.call(1)])", [E("mock_call", "assert_has_calls", exactness="call_args")]),
    ("assert_called_attr", "m = mock.Mock()\nm()\nassert m.called", [E("mock_call", "truthy", exactness="call_only", mock_only=True)]),
    ("assert_call_count", "m = mock.Mock()\nm()\nassert m.call_count == 1", [E("mock_call", "==", exactness="call_only", mock_only=True)]),
    ("assert_call_args", "m = mock.Mock()\nm(1)\nassert m.call_args == mock.call(1)", [E("mock_call", "==", exactness="call_args")]),
    ("assert_call_args_index", "m = mock.Mock()\nm(1)\nassert m.call_args[0][0] == 1", [E("mock_call", "==", mock_only=True)]),
    ("derived_from_created", "m = mock.Mock(return_value=5)\nr = m()\nassert r == 5", [E("equality", "==", mock_only=True)]),
    ("derived_mixed", "m = mock.Mock(return_value=5)\nr = m() + f(1)\nassert r == 5", [E("equality", mock_only=False)]),
    ("real_subject", "m = mock.Mock()\nassert f(1) == 2", [E("equality", mock_only=False)]),
    ("no_names", "assert 1 + 1 == 2", [E("equality", dead=False, mock_only=False)]),
]

SNAPSHOT_CASES: list[tuple[str, str, list]] = [
    ("syrupy", FULL + "def test_t(snapshot):\n    assert f(1) == snapshot", [E("snapshot", "==", snapshot_library="syrupy", exactness="snapshot", form="snapshot", framework="snapshot")]),
    ("syrupy_call", FULL + "def test_t(snapshot):\n    assert f(1) == snapshot(name='x')", [E("snapshot")]),
    ("syrupy_swapped", FULL + "def test_t(snapshot):\n    assert snapshot == f(1)", [E("snapshot", subject="f(1)")]),
    ("syrupy_json", FULL + "def test_t(snapshot_json):\n    assert f(1) == snapshot_json", [E("snapshot")]),
    ("pytest_snapshot", FULL + "def test_t(snapshot):\n    snapshot.assert_match(f(1), 'out.txt')", [E("snapshot", "assert_match", snapshot_library="pytest-snapshot")]),
    ("regressions", FULL + "def test_t(data_regression):\n    data_regression.check(f(1))", [E("snapshot", "check", snapshot_library="pytest-regressions")]),
    ("approval", FULL + "from approvaltests import verify\ndef test_t():\n    verify(f(1))", [E("snapshot", "verify", snapshot_library="approvaltests")]),
    ("approval_module", FULL + "import approvaltests\ndef test_t():\n    approvaltests.verify_as_json(f(1))", [E("snapshot", "verify_as_json")]),
    ("near_miss_name", "snapshot_id = g(1)\nassert f(1) == snapshot_id", [E("equality", "==")]),
    ("near_miss_attr", "r = g(1)\nassert f(1) == r.snapshot_version", [E("equality", "==")]),
    ("near_miss_verify_unimported", FULL + "def test_t():\n    verify(f(1))", []),
    ("near_miss_snapshot_not_fixture", FULL + "def test_t():\n    snapshot = g(1)\n    assert f(1) == snapshot", [E("equality", "==")]),
]

NUMPY_CASES: list[tuple[str, str, list]] = [
    ("np_array_equal", "import numpy as np\nnp.testing.assert_array_equal(f(1), [1, 2])", [E("equality", "assert_array_equal")]),
    ("np_allclose", "import numpy.testing as npt\nnpt.assert_allclose(f(1), [1.0], rtol=1e-3)", [E("approx", "assert_allclose", tolerance_rel=1e-3)]),
    ("np_isclose_assert", "import numpy as np\nassert np.allclose(f(1), 1.0, atol=0.1)", [E("approx", "allclose", tolerance_abs=0.1)]),
    ("pd_frame_equal", "import pandas as pd\npd.testing.assert_frame_equal(f(1), g(1))", [E("equality", "assert_frame_equal")]),
]

CASE_GROUPS = {
    "assert": ASSERT_CASES,
    "dead": DEAD_CASES,
    "raises": RAISES_CASES,
    "unittest": [(i, UNITTEST_BODY.format(c) if not c.startswith(FULL) else c, e) for i, c, e in UNITTEST_CASES],
    "mock": MOCK_CASES,
    "snapshot": SNAPSHOT_CASES,
    "numpy": NUMPY_CASES,
}
ALL_CASES = [pytest.param(code, exp, id=f"{group}-{cid}") for group, cases in CASE_GROUPS.items() for cid, code, exp in cases]


@pytest.mark.parametrize(("code", "expects"), ALL_CASES)
def test_assertion_table(code: str, expects: list) -> None:
    check(code, expects)


def test_table_has_at_least_one_hundred_cases() -> None:
    assert len(ALL_CASES) >= 100


# --------------------------------------------------------------------------- flags: loops, try, parametrize, hypothesis

FLAG_CASES = [
    ("for_loop", "for i in range(3):\n    assert f(i) == i", {"in_loop": True}),
    ("while_loop", "i = 0\nwhile i < 3:\n    assert f(i) == i\n    i += 1", {"in_loop": True}),
    ("async_for_like_nested", "for i in range(3):\n    if i:\n        assert f(i)", {"in_loop": True}),
    ("loop_else_not_in_loop", "for i in range(3):\n    pass\nelse:\n    assert f(1) == 1", {"in_loop": False}),
    ("no_loop", "assert f(1) == 1", {"in_loop": False}),
    ("swallow_assertionerror", "try:\n    assert f(1) == 2\nexcept AssertionError:\n    pass", {"swallowed": True}),
    ("swallow_exception", "try:\n    assert f(1) == 2\nexcept Exception:\n    print('x')", {"swallowed": True}),
    ("swallow_bare", "try:\n    assert f(1) == 2\nexcept:\n    pass", {"swallowed": True}),
    ("swallow_tuple", "try:\n    assert f(1) == 2\nexcept (ValueError, AssertionError):\n    pass", {"swallowed": True}),
    ("near_miss_specific_except", "try:\n    assert f(1) == 2\nexcept ValueError:\n    pass", {"swallowed": False}),
    ("near_miss_reraise", "try:\n    assert f(1) == 2\nexcept AssertionError:\n    raise", {"swallowed": False}),
    ("near_miss_finally_only", "try:\n    assert f(1) == 2\nfinally:\n    print('x')", {"swallowed": False}),
    ("assert_in_handler_not_swallowed", "try:\n    f(1)\nexcept Exception:\n    assert g(1) == 2", {"swallowed": False}),
    ("in_with_block", "with mock.patch('pkg.mod.g'):\n    assert f(1) == 2", {"in_loop": False, "swallowed": False}),
]


@pytest.mark.parametrize(("code", "feat"), [pytest.param(c, f, id=i) for i, c, f in FLAG_CASES])
def test_flags(code: str, feat: dict[str, Any]) -> None:
    recs = [r for r in run(code) if r.kind.value != "mock_call"]
    assert recs
    for r in recs:
        for k, v in feat.items():
            assert attr(r, k) == v, (k, r.subject_text)


PARAM_CASES = [
    ("edge_zero", '@pytest.mark.parametrize("a", [0, 1])\ndef test_t(a):\n    assert f(a) == a', True, 2),
    ("edge_none", '@pytest.mark.parametrize("a", [None, 1])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("edge_negative", '@pytest.mark.parametrize("a", [-1, 5])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("edge_empty_string", '@pytest.mark.parametrize("a", ["", "x"])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("edge_empty_list", '@pytest.mark.parametrize("a", [[], [1]])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("edge_tuple_params", '@pytest.mark.parametrize("a,b", [(2, 3), (0, 1)])\ndef test_t(a, b):\n    assert f(a, b)', True, 2),
    ("edge_pytest_param", '@pytest.mark.parametrize("a", [pytest.param(0, id="zero"), pytest.param(4)])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("edge_float_inf", '@pytest.mark.parametrize("a", [float("inf"), 2.5])\ndef test_t(a):\n    assert f(a)', True, 2),
    ("no_edge", '@pytest.mark.parametrize("a", [2, 3, 4])\ndef test_t(a):\n    assert f(a)', False, 3),
    ("one_is_not_edge", '@pytest.mark.parametrize("a", [1, 2])\ndef test_t(a):\n    assert f(a)', False, 2),
    ("non_literal_values", '@pytest.mark.parametrize("a", CASES)\ndef test_t(a):\n    assert f(a)', None, None),
    ("stacked_product", '@pytest.mark.parametrize("a", [1, 2])\n@pytest.mark.parametrize("b", [3, 4, 5])\ndef test_t(a, b):\n    assert f(a, b)', False, 6),
    ("unittest_parameterized", 'from parameterized import parameterized\n@parameterized.expand([(0,), (3,)])\ndef test_t(a):\n    assert f(a)', True, 2),
]


@pytest.mark.parametrize(("code", "edge", "cases"), [pytest.param(c, e, n, id=i) for i, c, e, n in PARAM_CASES])
def test_parametrize_edge_and_case_count(code: str, edge: bool | None, cases: int | None) -> None:
    path = "tests/test_t.py"
    res = extract_assertions([path], {path: build(FULL + code)})
    rec = res.assertions[0]
    assert rec.strength_features.in_parametrized is True
    assert rec.strength_features.edge_inputs is edge
    assert rec.strength_features.edge_input_source == "parametrize"
    assert res.tests[0].parametrized is True
    assert res.tests[0].case_count == cases


@pytest.mark.parametrize(
    ("code", "edge", "source"),
    [
        ("assert f(0) == 1", True, "call_args"),
        ("assert f(None) is None", True, "call_args"),
        ("assert f(5) == 6", False, "call_args"),
        ("x = g()\nassert f(x) == 6", None, None),
        ('assert f("") == 1', True, "call_args"),
    ],
)
def test_call_arg_edge_without_parametrize(code: str, edge: bool | None, source: str | None) -> None:
    rec = run(code)[0]
    assert rec.strength_features.edge_inputs is edge
    assert rec.strength_features.edge_input_source == source
    assert rec.strength_features.in_parametrized is False


def test_hypothesis_property_test_flagged() -> None:
    res = extract_assertions(
        ["tests/test_t.py"],
        {"tests/test_t.py": build(FULL + "from hypothesis import given, strategies as st\n@given(st.integers())\ndef test_t(x):\n    assert f(x) >= 0\n")},
    )
    rec = res.assertions[0]
    assert rec.strength_features.property_based is True
    assert rec.framework == "hypothesis"
    assert rec.strength_features.edge_inputs is None
    assert res.tests[0].property_based is True
    assert res.counts()["property_based_tests"] == 1


def test_hypothesis_dotted_decorator() -> None:
    rec = run(FULL + "import hypothesis\n@hypothesis.given(1)\ndef test_t(x):\n    assert f(x)\n")[0]
    assert rec.strength_features.property_based is True


# --------------------------------------------------------------------------- circular / dependence


@pytest.mark.parametrize(
    ("code", "circular"),
    [
        ("assert f(1) == f(1)", True),
        ("expected = f(2)\nassert f(2) == expected", True),
        ("assert f(1) == g(1)", False),
        ("assert f(1) == 3", False),
        ("r = f(1)\nassert r == r2()", False),
        ("r = f(1)\nassert r.a == r.b", False),
        ("assert len(f(1)) == len(f(2))", True),
        ("assert sorted(f(1)) == sorted([2, 1])", False),
        ("c = f(1)\nassert c == g(2)", False),
    ],
)
def test_circular_oracle(code: str, circular: bool) -> None:
    rec = next(r for r in run(code) if r.kind.value in {"equality", "length"})
    assert rec.strength_features.circular is circular


# --------------------------------------------------------------------------- discovery and helpers


def _ex(files: dict[str, str], paths: list[str] | None = None):  # noqa: ANN202
    return extract_assertions(paths or [p for p in files if "test_" in p.rsplit("/", 1)[-1]], files)


def test_helper_followed_depth_one() -> None:
    src = PRE + "def check(x):\n    assert x == 3\n\ndef test_t():\n    check(f(1))\n"
    res = _ex({"tests/test_t.py": src})
    (rec,) = res.assertions
    assert rec.test_id == "tests/test_t.py::test_t"
    assert rec.strength_features.helper_depth == 1
    assert rec.via and rec.via[0].startswith("check@")
    assert {r.qualified for r in rec.subject_refs} == {"pkg.mod.f"}  # via the argument binding
    assert rec.confidence < 0.95


def test_helper_followed_depth_two_not_three() -> None:
    src = PRE + (
        "def h3(x):\n    assert x == 3\n"
        "def h2(x):\n    assert x == 2\n    h3(x)\n"
        "def h1(x):\n    assert x == 1\n    h2(x)\n"
        "def test_t():\n    h1(f(1))\n"
    )
    res = _ex({"tests/test_t.py": src})
    depths = sorted(r.strength_features.helper_depth for r in res.assertions)
    assert depths == [1, 2]  # h3 would be depth 3: not followed


def test_helper_recursion_terminates() -> None:
    src = PRE + "def h(x):\n    assert x\n    h(x)\n\ndef test_t():\n    h(1)\n"
    res = _ex({"tests/test_t.py": src})
    assert len(res.assertions) == 1


def test_helper_called_twice_gives_distinct_records() -> None:
    src = PRE + "def check(x):\n    assert x == 3\n\ndef test_t():\n    check(1)\n    check(2)\n"
    res = _ex({"tests/test_t.py": src})
    assert len(res.assertions) == 2
    assert len({r.assertion_id for r in res.assertions}) == 2


def test_helper_shared_by_two_tests_is_attributed_to_each() -> None:
    src = PRE + "def check(x):\n    assert x == 3\n\ndef test_a():\n    check(1)\n\ndef test_b():\n    check(2)\n"
    res = _ex({"tests/test_t.py": src})
    assert sorted(r.test_id for r in res.assertions) == ["tests/test_t.py::test_a", "tests/test_t.py::test_b"]


def test_uncalled_helper_assertions_are_not_attributed() -> None:
    src = PRE + "def check(x):\n    assert x == 3\n\ndef test_a():\n    pass\n"
    res = _ex({"tests/test_t.py": src})
    assert res.assertions == ()
    assert res.tests_without_assertions == ("tests/test_t.py::test_a",)


def test_helper_inherits_loop_flag() -> None:
    src = PRE + "def check(x):\n    assert x == 3\n\ndef test_a():\n    for i in range(2):\n        check(i)\n"
    (rec,) = _ex({"tests/test_t.py": src}).assertions
    assert rec.strength_features.in_loop is True


def test_self_method_helper_in_class() -> None:
    src = PRE + "class TestX:\n    def _check(self, x):\n        assert x == 3\n\n    def test_a(self):\n        self._check(f(1))\n"
    (rec,) = _ex({"tests/test_t.py": src}).assertions
    assert rec.test_id == "tests/test_t.py::TestX::test_a"
    assert rec.strength_features.helper_depth == 1


def test_conftest_helper_followed() -> None:
    files = {
        "tests/conftest.py": "def check(x):\n    assert x == 3\n",
        "tests/test_t.py": PRE + "from conftest import check\ndef test_a():\n    check(f(1))\n",
    }
    (rec,) = _ex(files, ["tests/test_t.py"]).assertions
    assert rec.location.path == "tests/conftest.py"
    assert rec.test_id == "tests/test_t.py::test_a"


def test_nearest_conftest_wins() -> None:
    files = {
        "conftest.py": "def check(x):\n    assert x == 1\n",
        "tests/conftest.py": "def check(x):\n    assert x == 2\n",
        "tests/test_t.py": PRE + "def test_a():\n    check(f(1))\n",
    }
    (rec,) = _ex(files, ["tests/test_t.py"]).assertions
    assert rec.expected.text == "2"


def test_nested_local_helper() -> None:
    src = PRE + "def test_a():\n    def check(x):\n        assert x == 3\n    check(f(1))\n"
    (rec,) = _ex({"tests/test_t.py": src}).assertions
    assert rec.strength_features.helper_depth == 1


def test_discovery_rules() -> None:
    src = PRE + '''
import unittest

class TestPlain:
    def test_a(self):
        assert f(1)
    def helper(self):
        assert g(1)

class TestHasInit:
    def __init__(self):
        pass
    def test_never_collected(self):
        assert f(1)

class Helper:
    def test_not_a_test_class(self):
        assert f(1)

class Unit(unittest.TestCase):
    def test_u(self):
        self.assertTrue(f(1))
    def other(self):
        self.assertTrue(f(1))

class TestOuter:
    class TestInner:
        def test_deep(self):
            assert f(1)

class Base(unittest.TestCase):
    def test_inherited(self):
        self.assertTrue(f(1))

class Child(Base):
    def test_own(self):
        self.assertTrue(f(1))

async def test_async():
    assert f(1)

def not_a_test():
    assert f(1)

@pytest.fixture
def test_fixture_named_like_test():
    assert f(1)
'''
    res = _ex({"tests/test_t.py": src})
    ids = sorted(t.test_id.split("::", 1)[1] for t in res.tests)
    assert ids == sorted(
        [
            "TestPlain::test_a",
            "Unit::test_u",
            "TestOuter.TestInner::test_deep",
            "Base::test_inherited",
            "Child::test_inherited",
            "Child::test_own",
            "test_async",
        ]
    )


def test_no_assertion_and_unknown_assert_flags() -> None:
    src = PRE + "def test_a():\n    f(1)\n\ndef test_b():\n    pass\n\nclass T(unittest.TestCase):\n    def test_c(self):\n        self.assert_custom(f(1))\n"
    res = _ex({"tests/test_t.py": src})
    assert res.tests_without_assertions == ("tests/test_t.py::test_a", "tests/test_t.py::test_b")
    summary = {t.test_id: t for t in res.tests}["tests/test_t.py::T::test_c"]
    assert summary.has_dynamic_assertions is True
    assert summary.has_assertions is True


def test_counts_and_by_test() -> None:
    src = PRE + "def test_a():\n    assert True\n    assert f(1) == 2\n\ndef test_b():\n    pass\n"
    res = _ex({"tests/test_t.py": src})
    c = res.counts()
    assert c["tests"] == 2 and c["assertions"] == 2 and c["dead"] == 1 and c["tests_without_assertions"] == 1
    assert len(res.by_test()["tests/test_t.py::test_a"]) == 2
    assert len(res.for_test("tests/test_t.py::test_a")) == 2
