"""Unit tests for benchmark mutation operators (no network, no subprocess)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mutations  # noqa: E402

SRC = '''\
def f(xs, n):
    """Doc with 3 in it."""
    # comment kept
    total = 0
    for x in xs:
        if x < n:
            total = total + x
    while total > 100:
        total -= 1
    label = f"{total:03d}"
    if xs is None:
        return None
    return total - 1
'''


def _only(op: str) -> list[mutations.Site]:
    return [s for s in mutations.candidate_sites(SRC) if s.operator == op]


def _apply_all(op: str) -> list[str]:
    return [mutations.apply(SRC, s) for s in _only(op)]


def test_every_site_produces_valid_distinct_minimal_mutant() -> None:
    for site in mutations.candidate_sites(SRC):
        out = mutations.apply(SRC, site)
        ast.parse(out)
        assert out != SRC
        assert "# comment kept" in out  # rest of file untouched (no unparse round-trip)
        assert SRC.splitlines()[: site.lineno - 1] == out.splitlines()[: site.lineno - 1]


def test_flip_comparison() -> None:
    outs = _apply_all("flip_comparison")
    assert any("(x >= n)" in o for o in outs)
    assert any("(total <= 100)" in o for o in outs)
    assert any("(xs is not None)" in o for o in outs)


def test_negate_condition() -> None:
    outs = _apply_all("negate_condition")
    assert len(outs) == 3
    assert any("if not (x < n):" in o for o in outs)
    assert any("while not (total > 100):" in o for o in outs)


def test_off_by_one_skips_fstring_constants() -> None:
    outs = _apply_all("off_by_one")
    values = [s.lineno for s in _only("off_by_one")]
    assert 10 not in values  # f-string format spec is not a mutation site
    assert any("total = 1" in o for o in outs)
    assert any("total -= 2" in o for o in outs)
    assert any("return total - 2" in o for o in outs)


def test_return_none_skips_existing_none() -> None:
    sites = _only("return_none")
    assert [s.lineno for s in sites] == [13]
    assert mutations.apply(SRC, sites[0]).rstrip().endswith("return None")


def test_swap_add_sub() -> None:
    outs = _apply_all("swap_add_sub")
    assert any("total = (total - x)" in o for o in outs)
    assert any("return (total + 1)" in o for o in outs)


def test_sample_is_deterministic_and_seed_sensitive() -> None:
    files = {"a.py": SRC, "b.py": "def g(a):\n    return a + 1\n"}
    a = mutations.sample(files, 5, seed=7)
    assert a == mutations.sample(files, 5, seed=7)
    assert len(a) == 5
    assert a != mutations.sample(files, 5, seed=8)
    total = len(mutations.candidate_sites(SRC)) + len(mutations.candidate_sites(files["b.py"]))
    assert len(mutations.sample(files, 10_000, seed=1)) == total


def test_unicode_column_offsets() -> None:
    src = 'def h(s):\n    return "é" + s if len(s) > 0 else s\n'
    for site in mutations.candidate_sites(src):
        out = mutations.apply(src, site)
        ast.parse(out)
        assert out.startswith("def h(s):\n    return ")
        if site.operator != "return_none":
            assert "é" in out and out.rstrip().endswith("else s")
