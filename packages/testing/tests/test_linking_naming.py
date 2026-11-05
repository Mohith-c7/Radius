"""Naming/convention linker tests (LK-03)."""

from __future__ import annotations

import pytest
from radius_testing.linking import LinkTarget, NamingLinker
from radius_testing.linking.naming import NAMING_CAP, file_match

CASES = [
    # name, target path, qualname, kind, files {path: source}, expected {test_id: (min, max)}
    ("test_file_and_function", "src/pricing.py", "apply_discount", "function",
     {"tests/test_pricing.py": "def test_apply_discount():\n    pass\n\ndef test_other():\n    pass\n"},
     {"tests/test_pricing.py::test_apply_discount": (0.6, 0.6), "tests/test_pricing.py::test_other": (0.15, 0.25)}),
    ("function_suffix_variant", "src/pricing.py", "apply_discount", "function",
     {"tests/test_pricing.py": "def test_apply_discount_negative():\n    pass\n"},
     {"tests/test_pricing.py::test_apply_discount_negative": (0.6, 0.6)}),
    ("function_match_wrong_file", "src/pricing.py", "apply_discount", "function",
     {"tests/test_misc.py": "def test_apply_discount():\n    pass\n"},
     {"tests/test_misc.py::test_apply_discount": (0.3, 0.3)}),
    ("short_function_name_weak", "src/pricing.py", "run", "function",
     {"tests/test_misc.py": "def test_run():\n    pass\n"},
     {"tests/test_misc.py::test_run": (0.1, 0.2)}),
    ("class_method_convention", "src/cart.py", "Cart.add", "method",
     {"tests/test_cart.py": "class TestCart:\n    def test_add(self):\n        pass\n\n    def test_remove(self):\n        pass\n"},
     {"tests/test_cart.py::TestCart::test_add": (0.6, 0.6), "tests/test_cart.py::TestCart::test_remove": (0.3, 0.4)}),
    ("class_target_test_class", "src/cart.py", "Cart", "class",
     {"tests/test_cart.py": "class TestCart:\n    def test_a(self):\n        pass\n"},
     {"tests/test_cart.py::TestCart::test_a": (0.5, 0.6)}),
    ("unittest_camel_case", "src/cart.py", "Cart.add", "method",
     {"tests/test_cart.py": "import unittest\n\nclass CartTest(unittest.TestCase):\n    def testAdd(self):\n        pass\n"},
     {"tests/test_cart.py::CartTest::testAdd": (0.6, 0.6)}),
    ("same_dir_test_file", "pkg/util.py", "slug", "function",
     {"pkg/test_util.py": "def test_slug():\n    pass\n"},
     {"pkg/test_util.py::test_slug": (0.6, 0.6)}),
    ("suffix_test_file", "pkg/util.py", "slug", "function",
     {"tests/util_test.py": "def test_slug():\n    pass\n"},
     {"tests/util_test.py::test_slug": (0.6, 0.6)}),
    ("mirror_path_subpackage", "src/pkg/sub/util.py", "slug", "function",
     {"tests/sub/test_util.py": "def test_slug():\n    pass\n"},
     {"tests/sub/test_util.py::test_slug": (0.6, 0.6)}),
    ("unrelated_test_no_link", "src/pricing.py", "apply_discount", "function",
     {"tests/test_other.py": "def test_something_else():\n    pass\n"},
     {}),
    ("module_level_target", "src/pricing.py", "<module>", "module",
     {"tests/test_pricing.py": "def test_a():\n    pass\n"},
     {"tests/test_pricing.py::test_a": (0.15, 0.25)}),
    ("init_module_uses_package_name", "src/pkg/__init__.py", "make", "function",
     {"tests/test_pkg.py": "def test_make():\n    pass\n"},
     {"tests/test_pkg.py::test_make": (0.6, 0.6)}),
    ("typescript_test_file", "src/util.ts", "slug", "function",
     {"src/util.test.ts": "it('x', () => {})\n"},
     {"src/util.test.ts::x": (0.15, 0.25)}),
]


@pytest.mark.parametrize(("name", "path", "qual", "kind", "files", "expected"), CASES, ids=[c[0] for c in CASES])
def test_naming_cases(name, path, qual, kind, files, expected):
    language = "typescript" if path.endswith(".ts") else "python"
    tgt = LinkTarget(f"{language}:{path}::{qual}", path, qual, kind, language)
    sources = dict(files)
    sources[path] = "x = 1\n" if path.endswith(".py") else "export const x = 1\n"
    result = NamingLinker().link(sources, [tgt])
    by_test = {link.test_id: link for link in result.links}
    assert set(by_test) == set(expected), (sorted(by_test), result.links)
    for test_id, (lo, hi) in expected.items():
        assert lo <= by_test[test_id].score <= hi, (test_id, by_test[test_id].score)
        assert by_test[test_id].kind.value == "name_convention"
        assert by_test[test_id].linker == "naming"


def test_scores_are_capped():
    tgt = LinkTarget("python:src/p.py::f_long_name", "src/p.py", "f_long_name")
    files = {"src/p.py": "", "tests/test_p.py": "def test_f_long_name():\n    pass\n"}
    assert all(link.score <= NAMING_CAP for link in NamingLinker().link(files, [tgt]).links)


def test_tie_break_prefers_longest_matching_name():
    a = LinkTarget("python:src/p.py::apply", "src/p.py", "apply")
    b = LinkTarget("python:src/p.py::apply_discount", "src/p.py", "apply_discount")
    files = {"src/p.py": "", "tests/test_p.py": "def test_apply_discount_negative():\n    pass\n"}
    links = {(lk.symbol_id, lk.test_id) for lk in NamingLinker().link(files, [a, b]).links}
    assert (b.symbol_id, "tests/test_p.py::test_apply_discount_negative") in links
    assert (a.symbol_id, "tests/test_p.py::test_apply_discount_negative") not in links


def test_same_name_in_two_files_ranked_by_file_match():
    a = LinkTarget("python:src/a.py::process_order", "src/a.py", "process_order")
    b = LinkTarget("python:src/b.py::process_order", "src/b.py", "process_order")
    files = {"src/a.py": "", "src/b.py": "", "tests/test_a.py": "def test_process_order():\n    pass\n"}
    by_symbol = {lk.symbol_id: lk.score for lk in NamingLinker().link(files, [a, b]).links}
    assert by_symbol[a.symbol_id] > by_symbol[b.symbol_id]


def test_works_when_static_finds_nothing():
    from radius_testing.linking import StaticLinker

    files = {
        "src/p.py": "def run_job():\n    pass\n",
        "tests/test_p.py": "import importlib\n\ndef test_run_job():\n    importlib.import_module('p').run_job()\n",
    }
    tgt = LinkTarget("python:src/p.py::run_job", "src/p.py", "run_job")
    static = [lk for lk in StaticLinker().link(files, [tgt]).links if lk.score >= 0.3]
    naming = NamingLinker().link(files, [tgt]).links
    assert static == []
    assert naming and naming[0].score >= 0.6


def test_file_match_levels():
    assert file_match("src/pricing.py", "tests/test_pricing.py") == 2
    assert file_match("src/pkg/pricing.py", "tests/pkg/test_pricing.py") == 2
    assert file_match("src/pkg/pricing.py", "tests/other/test_pricing.py") == 1
    assert file_match("src/pricing.py", "tests/test_other.py") == 0
    assert file_match("src/pricing.py", "tests/test_pricing_edge.py") == 1


def test_deterministic():
    tgt = LinkTarget("python:src/p.py::f_long_name", "src/p.py", "f_long_name")
    files = {"src/p.py": "", "tests/test_p.py": "def test_f_long_name():\n    pass\n\ndef test_z():\n    pass\n"}
    first = NamingLinker().link(files, [tgt]).to_json()
    assert NamingLinker().link(dict(reversed(list(files.items()))), [tgt]).to_json() == first
