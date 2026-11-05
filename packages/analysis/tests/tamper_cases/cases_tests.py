"""Table-driven cases for the test-level rules T001-T008 (EV-02).

Each case: base/head file maps, the exact ``rule:check`` list the whole report must contain
(``[]`` = negative or near-miss) and the rule it documents.
"""

from textwrap import dedent as D

SRC = D(
    """
    def total(xs):
        return sum(xs)


    def price(n):
        return n * 2
    """
)
SRC_PRICE_CHANGED = SRC.replace("n * 2", "n * 3")
SRC_PRICE_DOC = SRC.replace("return n * 2", '"""Double it."""\n    return n * 2')


def c(id, rule, base, head, expect=(), **kw):
    return dict(id=id, rule=rule, base=base, head=head, expect=list(expect), **kw)


def tf(body, header="import pytest\nfrom shop import total, price\n\n\n"):
    return header + D(body)


T_BASE2 = tf(
    """
    def test_total():
        assert total([1, 2]) == 3


    def test_price():
        assert price(2) == 4
    """
)

CASES = [
    # ------------------------------------------------------------------ T001
    c("t001-deleted", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_total():\n    assert total([1, 2]) == 3\n")},
      ["T001:test_deleted"]),
    c("t001-file-deleted", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC}, ["T001:test_deleted", "T001:test_deleted"]),
    c("t001-method-deleted", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "class TestShop:\n    def test_a(self):\n        assert total([1]) == 1\n\n"
          "    def test_b(self):\n        assert price(1) == 2\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "class TestShop:\n    def test_a(self):\n        assert total([1]) == 1\n")},
      ["T001:test_deleted"]),
    c("t001-param-removed", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          '@pytest.mark.parametrize("n,e", [(1, 2), (2, 4), (3, 6)])\n'
          "def test_price(n, e):\n    assert price(n) == e\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          '@pytest.mark.parametrize("n,e", [(1, 2), (2, 4)])\n'
          "def test_price(n, e):\n    assert price(n) == e\n")},
      ["T001:parametrize_case_removed"]),
    c("t001-commented-out", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_total():\n    assert total([1, 2]) == 3\n\n\n"
          "# def test_price():\n#     assert price(2) == 4\n")},
      ["T001:commented_out_test"]),
    c("t001-sut-removed-too", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC.split("\n\n\ndef price")[0] + "\n",
       "tests/test_shop.py": tf("def test_total():\n    assert total([1, 2]) == 3\n")}, []),
    c("t001-test-added", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + "\n\ndef test_zero():\n    assert total([]) == 0\n"}, []),
    c("t001-param-value-changed-same-count", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          '@pytest.mark.parametrize("n,e", [(1, 2), (2, 4)])\ndef test_price(n, e):\n    assert price(n) == e\n')},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          '@pytest.mark.parametrize("n,e", [(1, 2), (5, 10)])\ndef test_price(n, e):\n    assert price(n) == e\n')}, []),
    c("t001-moved-to-other-file", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2, "tests/test_more.py": tf("def test_x():\n    assert total([]) == 0\n")},
      {"src/shop.py": SRC,
       "tests/test_shop.py": tf("def test_total():\n    assert total([1, 2]) == 3\n"),
       "tests/test_more.py": tf(
           "def test_x():\n    assert total([]) == 0\n\n\ndef test_price():\n    assert price(2) == 4\n")}, []),
    c("t001-renamed-same-body", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("def test_price", "def test_price_doubles")}, []),
    c("t001-renamed-and-edited", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price():\n    assert price(2) == 4",
          "def test_price_doubles_the_input():\n    assert price(2) == 4\n    assert price(3) == 6")}, []),
    c("t001-renamed-and-moved-to-other-file", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2, "tests/test_more.py": tf("def test_x():\n    assert total([]) == 0\n")},
      {"src/shop.py": SRC,
       "tests/test_shop.py": tf("def test_total():\n    assert total([1, 2]) == 3\n"),
       "tests/test_more.py": tf(
           "def test_x():\n    assert total([]) == 0\n\n\ndef test_price_moved():\n    assert price(2) == 4\n")}, []),
    c("t001-delete-plus-unrelated-add-still-fires", "T001", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_total():\n    assert total([1, 2]) == 3\n\n\n"
          "def test_empty_total():\n    assert total([]) == 0\n")},
      ["T001:test_deleted"]),
    c("t001-rename-that-drops-all-assertions-still-fires", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price():\n    assert price(2) == 4", "def test_price_renamed():\n    price(2)")},
      ["T001:test_deleted"]),
    c("t001-one-added-test-cannot-explain-two-deletions", "T001",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_price_a():\n    assert price(2) == 4\n\n\ndef test_price_b():\n    assert price(2) == 4\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_price_c():\n    assert price(2) == 4\n")},
      ["T001:test_deleted"]),
    # ------------------------------------------------------------------ T002
    c("t002-skip", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price", '@pytest.mark.skip(reason="later")\ndef test_price')}, ["T002:skip"]),
    c("t002-xfail", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price", "@pytest.mark.xfail\ndef test_price")}, ["T002:xfail"]),
    c("t002-skipif", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price", '@pytest.mark.skipif(True, reason="x")\ndef test_price')}, ["T002:skipif"]),
    c("t002-unittest-skip", "T002",
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(price(1), 2)\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    @unittest.skip('no')\n    def test_a(self):\n        self.assertEqual(price(1), 2)\n"},
      ["T002:skip"]),
    c("t002-runtime-skip", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", '    pytest.skip("later")\n    assert price(2) == 4')},
      ["T002:runtime_skip"]),
    c("t002-if-false", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    if False:\n        assert price(2) == 4")},
      ["T002:runtime_skip"]),
    c("t002-module-skip", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "\n\n\ndef test_total", "\n\npytestmark = pytest.mark.skip\n\n\ndef test_total", 1)},
      ["T002:module_skip"]),
    c("t002-class-skip-once", "T002",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "class TestShop:\n    def test_a(self):\n        assert total([1]) == 1\n\n"
          "    def test_b(self):\n        assert price(1) == 2\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "@pytest.mark.skip\nclass TestShop:\n    def test_a(self):\n        assert total([1]) == 1\n\n"
          "    def test_b(self):\n        assert price(1) == 2\n")},
      ["T002:skip"]),
    c("t002-existing-skip-unchanged", "T002",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("def test_price", "@pytest.mark.skip\ndef test_price")},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("def test_price", "@pytest.mark.skip\ndef test_price")
       + "\n\ndef test_zero():\n    assert total([]) == 0\n"}, []),
    c("t002-other-marker", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price", "@pytest.mark.slow\ndef test_price")}, []),
    c("t002-skip-in-string", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", '    note = "pytest.mark.skip"\n    assert price(2) == 4')}, []),
    c("t002-runtime-skip-new-test-unconditional", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + '\n\ndef test_zero():\n    pytest.skip("later")\n    assert total([]) == 0\n'},
      ["T002:runtime_skip_new"]),
    c("t002-runtime-skip-platform-guard", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4",
          '    if sys.platform == "win32":\n        pytest.skip("posix only")\n    assert price(2) == 4').replace(
          "import pytest", "import sys\n\nimport pytest")},
      ["T002:runtime_skip_guarded"]),
    c("t002-runtime-skip-env-guard", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4",
          '    if not os.environ.get("RUN_SLOW"):\n        pytest.skip("slow")\n    assert price(2) == 4').replace(
          "import pytest", "import os\n\nimport pytest")},
      ["T002:runtime_skip_guarded"]),
    c("t002-runtime-skip-optional-import", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4",
          '    try:\n        import prometheus_client\n    except ImportError:\n        pytest.skip("prometheus_client not installed")\n    assert price(2) == 4')},
      ["T002:runtime_skip_guarded"]),
    c("t002-runtime-skip-file-missing-guard-in-new-test", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + '\n\ndef test_spec(tmp_path):\n    if not (tmp_path / "openapi.json").exists():\n        pytest.skip("no previous spec")\n    assert total([]) == 0\n'},
      ["T002:runtime_skip_guarded"]),
    c("t002-runtime-skip-data-dependent-condition", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4",
          '    if price(2) != 4:\n        pytest.skip("odd")\n    assert price(2) == 4')},
      ["T002:runtime_skip_conditional"]),
    c("t002-importorskip-is-not-a-skip-finding", "T002", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", '    pytest.importorskip("numpy")\n    assert price(2) == 4')}, []),
    c("t002-existing-guarded-skip-unchanged", "T002",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", '    if sys.platform == "win32":\n        pytest.skip("posix")\n    assert price(2) == 4').replace("import pytest", "import sys\n\nimport pytest")},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", '    if sys.platform == "win32":\n        pytest.skip("posix")\n    assert price(2) == 4').replace("import pytest", "import sys\n\nimport pytest")
       + "\n\ndef test_zero():\n    assert total([]) == 0\n"}, []),
    # ------------------------------------------------------------------ T003
    c("t003-assertion-removed", "T003",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_total():\n    assert total([1, 2]) == 3\n    assert total([]) == 0\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_total():\n    assert total([1, 2]) == 3\n")}, ["T003:assertion_removed"]),
    c("t003-body-pass", "T003", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("    assert price(2) == 4", "    pass")},
      ["T003:body_emptied"]),
    c("t003-body-ellipsis", "T003", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("    assert price(2) == 4", "    ...")},
      ["T003:body_emptied"]),
    c("t003-commented-assertion", "T003", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    # assert price(2) == 4\n    price(2)")},
      ["T003:assertion_removed", "T003:commented_out_assertion"]),
    c("t003-split-into-two-tests", "T003",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_both():\n    assert total([1]) == 1\n    assert price(1) == 2\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "def test_both():\n    assert total([1]) == 1\n\n\ndef test_price_only():\n    assert price(1) == 2\n")},
      []),
    c("t003-assertion-added", "T003", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    assert price(2) == 4\n    assert price(0) == 0")}, []),
    c("t003-same-count-replaced", "T003", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(3) == 6")}, []),
    c("t003-stub-test-in-base", "T003",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_todo():\n    pass\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_todo():\n    pass\n\n\ndef test_new():\n    assert total([]) == 0\n")},
      []),
    # ------------------------------------------------------------------ T004
    c("t004-not-none", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) is not None")},
      ["T004:strength_reduced"]),
    c("t004-truthy", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert price(2)")},
      ["T004:strength_reduced"]),
    c("t004-membership", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) in (4, 5, 6)")},
      ["T004:strength_reduced"]),
    c("t004-ordering", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) >= 0")},
      ["T004:strength_reduced"]),
    c("t004-isinstance", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert isinstance(price(2), int)")},
      ["T004:strength_reduced"]),
    c("t004-approx-widened", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == pytest.approx(4.0, rel=1e-6)\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == pytest.approx(4.0, rel=0.5)\n")},
      ["T004:tolerance_widened"]),
    c("t004-almost-equal-places", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    def test_p(self):\n        self.assertAlmostEqual(price(2), 4.0, places=7)\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    def test_p(self):\n        self.assertAlmostEqual(price(2), 4.0, places=1)\n"},
      ["T004:tolerance_widened"]),
    c("t004-unittest-equal-to-true", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    def test_p(self):\n        self.assertEqual(price(2), 4)\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": "import unittest\nfrom shop import price\n\n\nclass T(unittest.TestCase):\n    def test_p(self):\n        self.assertTrue(price(2))\n"},
      ["T004:strength_reduced"]),
    c("t004-conjunct-dropped", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == 4 and price(1) == 2\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == 4\n")},
      ["T004:conjunct_dropped"]),
    c("t004-conjunct-split-into-asserts", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    title = str(price(2))\n    assert title.startswith('4') and 'old' in title\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    title = str(price(2))\n    assert title.startswith('4')\n    assert 'new' in title\n")},
      []),
    c("t004-strengthened", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) is not None\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == 4\n")}, []),
    c("t004-reformatted", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert (  price( 2 )==4 )")}, []),
    c("t004-literal-changed-sut-unchanged", "T004", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == 5")}, []),
    c("t004-approx-tightened", "T004",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == pytest.approx(4.0, rel=0.5)\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    assert price(2) == pytest.approx(4.0, rel=1e-6)\n")},
      []),
    # ------------------------------------------------------------------ T005
    c("t005-assert-true", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert True")},
      ["T005:always_true"]),
    c("t005-self-compare", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == price(2)")},
      ["T005:self_comparison"]),
    c("t005-not-false", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert not False")},
      ["T005:always_true"]),
    c("t005-constant-one", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", "assert 1")},
      ["T005:always_true"]),
    c("t005-unittest-true", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    import unittest\n    unittest.TestCase().assertTrue(True)")},
      ["T005:always_true"]),
    c("t005-or-true", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == 4 or True")},
      ["T005:always_true"]),
    c("t005-tuple-assert", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("assert price(2) == 4", 'assert (price(2) == 4, "msg")')},
      ["T005:always_true"]),
    c("t005-new-test-added", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + "\n\ndef test_new():\n    assert total([1]) == total([1])\n"},
      ["T005:self_comparison"]),
    c("t005-preexisting-unchanged", "T005",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_a():\n    assert True\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_a():\n    assert True\n\n\ndef test_b():\n    assert price(2) == 4\n")},
      []),
    c("t005-real-comparison", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == price(1) * 2")}, []),
    c("t005-assert-in-source-file", "T005", {"src/shop.py": SRC},
      {"src/shop.py": SRC + "\n\ndef check():\n    assert True\n"}, []),
    c("t005-is-true", "T005", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "bool(price(2)) is True")}, []),
    # ------------------------------------------------------------------ T006
    c("t006-expected-changed", "T006", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC_PRICE_CHANGED, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == 6")},
      ["T006:expected_literal_changed"]),
    c("t006-snapshot-updated", "T006",
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2, "tests/__snapshots__/price.snap": "price=4\n"},
      {"src/shop.py": SRC_PRICE_CHANGED, "tests/test_shop.py": T_BASE2, "tests/__snapshots__/price.snap": "price=6\n"},
      ["T006:snapshot_updated"]),
    c("t006-source-unchanged", "T006", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == 6")}, []),
    c("t006-new-test-for-changed-source", "T006", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC_PRICE_CHANGED, "tests/test_shop.py": T_BASE2 + "\n\ndef test_new():\n    assert price(3) == 9\n"}, []),
    c("t006-docstring-only-source-change", "T006", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC_PRICE_DOC, "tests/test_shop.py": T_BASE2.replace("price(2) == 4", "price(2) == 6")}, []),
    c("t006-snapshot-added-new", "T006", {"src/shop.py": SRC},
      {"src/shop.py": SRC_PRICE_CHANGED, "tests/__snapshots__/price.snap": "price=6\n"}, []),
    # ------------------------------------------------------------------ T007
    c("t007-try-except-pass", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    try:\n        assert price(2) == 4\n    except Exception:\n        pass")},
      ["T007:test_swallow"]),
    c("t007-bare-except", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    try:\n        assert price(2) == 4\n    except:\n        pass")},
      ["T007:test_swallow"]),
    c("t007-assertion-error", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    try:\n        assert price(2) == 4\n    except AssertionError:\n        pass")},
      ["T007:swallows_assertion"]),
    c("t007-raises-broadened", "T007",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    with pytest.raises(ValueError):\n        price(-1)\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_p():\n    with pytest.raises(Exception):\n        price(-1)\n")},
      ["T007:raises_broadened"]),
    c("t007-raises-broad-new", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + "\n\ndef test_n():\n    with pytest.raises(Exception):\n        price(None)\n"},
      ["T007:raises_broad"]),
    c("t007-source-swallow", "T007", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("    return n * 2", "    try:\n        return n * 2\n    except Exception:\n        pass")},
      ["T007:source_broad_swallow"]),
    c("t007-specific-handler-logs", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "    assert price(2) == 4", "    try:\n        assert price(2) == 4\n    except ValueError:\n        print('x')")}, []),
    c("t007-raises-specific", "T007", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2 + "\n\ndef test_n():\n    with pytest.raises(TypeError):\n        price(None)\n"}, []),
    c("t007-handler-reraises", "T007", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("    return n * 2", "    try:\n        return n * 2\n    except Exception:\n        raise")}, []),
    c("t007-importerror-fallback", "T007", {"src/shop.py": SRC},
      {"src/shop.py": "try:\n    import ujson as json\nexcept ImportError:\n    json = None\n" + SRC}, []),
    c("t007-swallow-unchanged", "T007",
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_a():\n    try:\n        assert price(1) == 2\n    except Exception:\n        pass\n")},
      {"src/shop.py": SRC, "tests/test_shop.py": tf("def test_a():\n    try:\n        assert price(1) == 2\n    except Exception:\n        pass\n\n\ndef test_b():\n    assert total([]) == 0\n")},
      []),
    # ------------------------------------------------------------------ T008
    c("t008-patches-sut-decorator", "T008", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.price", return_value=4)\ndef test_price(m):\n    assert price(2) == 4\n\n\n'
          "def test_total():\n    assert total([1, 2]) == 3\n")},
      ["T008:patches_unit_under_test"]),
    c("t008-monkeypatch", "T008", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price():", "def test_price(monkeypatch):\n    monkeypatch.setattr('shop.price', lambda n: 4)")},
      ["T008:patches_unit_under_test"]),
    c("t008-autospec-removed", "T008",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.helper", autospec=True)\ndef test_total(m):\n    assert total([1]) == 1\n')},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.helper")\ndef test_total(m):\n    assert total([1]) == 1\n')},
      ["T008:autospec_removed"]),
    c("t008-assert-on-mock", "T008", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2.replace(
          "def test_price():\n    assert price(2) == 4",
          "def test_price():\n    from unittest.mock import MagicMock\n    fake = MagicMock(return_value=4)\n    assert fake(2) == 4")},
      ["T008:asserts_on_mock"]),
    c("t008-patches-collaborator", "T008", {"src/shop.py": SRC, "tests/test_shop.py": T_BASE2},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.send_email")\ndef test_total(m):\n    assert total([1, 2]) == 3\n\n\n'
          "def test_price():\n    assert price(2) == 4\n")}, []),
    c("t008-patch-preexisting", "T008",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.price")\ndef test_a(m):\n    m.return_value = 1\n    assert price(1) == 1\n')},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.price")\ndef test_a(m):\n    m.return_value = 1\n    assert price(1) == 1\n\n\n'
          "def test_b():\n    assert total([]) == 0\n")}, []),
    c("t008-autospec-kept", "T008",
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.helper", autospec=True)\ndef test_total(m):\n    assert total([1]) == 1\n')},
      {"src/shop.py": SRC, "tests/test_shop.py": tf(
          "from unittest.mock import patch\n\n\n"
          '@patch("shop.helper", autospec=True)\ndef test_total(m):\n    assert total([1, 2]) == 3\n')}, []),
]
