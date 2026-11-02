"""Budget/sampling, kill matrix, d_mut math, equivalent-mutant detector."""

from __future__ import annotations

import dataclasses

import pytest
from radius_testing.mutation import (
    KillMatrix,
    MutantRecord,
    aggregate_criterion,
    cache_key,
    d_mut_per_test,
    detect_equivalent,
    generate_mutants,
    sample_mutants,
    wilson_interval,
)
from radius_testing.mutation.budget import MutationBudget


def _rec(i, status, killers=(), suspect=False, symbol="f"):
    return MutantRecord(
        id=f"m{i}", symbol=symbol, operator="ROR", status=status,
        killed_by=frozenset(killers), equivalent_suspect=suspect,
    )


def _matrix() -> KillMatrix:
    return KillMatrix(
        records=(
            _rec(1, "killed", ["t1", "t2"]),
            _rec(2, "killed", ["t1"]),
            _rec(3, "killed", ["t1"]),
            _rec(4, "survived"),
            _rec(5, "killed", ["t2"]),
            _rec(6, "survived", suspect=True),
            _rec(7, "timeout"),
            _rec(8, "killed", ["t3"], symbol="other"),
        ),
        tests=("t1", "t2", "t3"),
    )


def test_wilson_hand_values() -> None:
    lo, hi = wilson_interval(3, 5)
    assert lo == pytest.approx(0.2307, abs=2e-3)
    assert hi == pytest.approx(0.8824, abs=2e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = wilson_interval(5, 5)
    assert hi == 1.0 and lo == pytest.approx(0.5655, abs=2e-3)
    lo, hi = wilson_interval(0, 5)
    assert lo == 0.0 and hi == pytest.approx(0.4345, abs=2e-3)


def test_d_mut_per_test_multi_credit() -> None:
    # symbol f: non-equivalent decided = m1..m5 (m6 suspect, m7 timeout excluded) -> n = 5
    got = {d.test: d for d in d_mut_per_test(_matrix(), ["f"], min_mutants=5)}
    assert got["t1"].n == 5 and got["t1"].killed == 3 and got["t1"].d_mut == pytest.approx(0.6)
    assert got["t2"].d_mut == pytest.approx(0.4)
    assert got["t3"].d_mut == 0.0 and got["t3"].lcb == 0.0
    assert got["t1"].lcb == pytest.approx(0.2307, abs=2e-3)
    assert got["t1"].ucb == pytest.approx(0.8824, abs=2e-3)


def test_d_mut_split_credit() -> None:
    got = {d.test: d for d in d_mut_per_test(_matrix(), ["f"], credit="split")}
    assert got["t1"].killed == pytest.approx(2.5) and got["t1"].d_mut == pytest.approx(0.5)
    assert got["t2"].killed == pytest.approx(1.5) and got["t2"].d_mut == pytest.approx(0.3)
    with pytest.raises(ValueError):
        d_mut_per_test(_matrix(), ["f"], credit="bogus")


def test_minimum_sample_guard_returns_none() -> None:
    got = d_mut_per_test(_matrix(), ["f"], min_mutants=6)
    assert all(d.d_mut is None and d.reason == "insufficient_sample" for d in got)
    # the symbol with a single mutant never yields a number
    assert d_mut_per_test(_matrix(), ["other"])[2].d_mut is None


def test_suspects_policy_changes_the_denominator() -> None:
    inc = {d.test: d for d in d_mut_per_test(_matrix(), ["f"], exclude_suspects=False)}
    assert inc["t1"].n == 6 and inc["t1"].d_mut == pytest.approx(0.5)


def test_criterion_aggregation_union_and_survivors() -> None:
    agg = aggregate_criterion(_matrix(), ["f"], ["t1", "t2"])
    assert agg.n_mutants == 5 and agg.killed_by_any == 4
    assert agg.union_d == pytest.approx(0.8)
    assert agg.survivors == ("m4",)
    assert agg.excluded == {"equivalent_suspect": ["m6"], "timeout": ["m7"]}
    only_t2 = aggregate_criterion(_matrix(), ["f"], ["t2"])
    assert only_t2.killed_by_any == 2 and only_t2.union_d == pytest.approx(0.4)
    small = aggregate_criterion(_matrix(), ["other"], ["t3"])
    assert small.union_d is None and small.reason == "insufficient_sample"


def test_sampling_is_deterministic_stratified_and_budgeted() -> None:
    src = "def f(a):\n    return a + 1 + 2 + 3\n\n\ndef g(a):\n    return a * 2\n"
    ms = generate_mutants(src, "m.py", operators=["AOR", "CON"])
    assert len(ms) > 4
    assert sample_mutants(ms, 100) == ms
    assert sample_mutants(ms, 0) == []
    a = sample_mutants(ms, 4, seed=7)
    assert a == sample_mutants(ms, 4, seed=7) and len(a) == 4
    assert [m.id for m in a] == [m.id for m in ms if m.id in {x.id for x in a}]  # canonical order
    assert {"f", "g"} <= {m.symbol for m in a}  # small symbol not starved
    others = {tuple(m.id for m in sample_mutants(ms, 4, seed=s)) for s in range(8)}
    assert len(others) > 1  # the seed matters


def test_budget_validation_and_cache_key() -> None:
    with pytest.raises(ValueError):
        MutationBudget(max_mutants=-1)
    with pytest.raises(ValueError):
        MutationBudget(wall_clock_seconds=0)
    k = cache_key("h", ["b", "a"], "sha256:img")
    assert k == cache_key("h", ["a", "b", "a"], "sha256:img")
    assert k != cache_key("h2", ["a", "b"], "sha256:img")
    assert k != cache_key("h", ["a"], "sha256:img")
    assert k != cache_key("h", ["a", "b"], "sha256:other")


def _equiv(src: str, op: str):
    return [
        (m, detect_equivalent(src, m))
        for m in generate_mutants(src, "m.py", operators=[op])
    ]


def test_equivalent_neutral_operand_and_identical_operands() -> None:
    (m, v), = _equiv("def f(x):\n    return x + 0\n", "AOR")
    assert v.suspect and v.method == "pattern"
    (m, v), = _equiv("def f(x):\n    return x * 1\n", "AOR")
    assert v.suspect
    got = _equiv("def f(a):\n    return a and a\n", "BOOL")
    assert all(v.suspect for _, v in got)
    # swapping identical arguments is a textual no-op: the generator drops it outright
    assert _equiv("def f(a):\n    return g(a, a)\n", "ARG") == []


def test_equivalent_logging_and_message_patterns() -> None:
    (m, v), = _equiv("def f(x):\n    print(x)\n", "CALL")
    assert v.suspect and "logging" in (v.reason or "")
    (m, v), = _equiv("def f(x):\n    logger.info(x)\n", "CALL")
    assert v.suspect
    (m, v), = _equiv("def f(x):\n    do(x)\n", "CALL")
    assert not v.suspect
    (m, v), = _equiv("def f(x):\n    raise ValueError('bad')\n", "CON")
    assert v.suspect and v.reason == "exception message constant"


def test_non_equivalent_mutants_are_not_flagged() -> None:
    for src, op in (
        ("def f(a, b):\n    return a < b\n", "ROR"),
        ("def f(a, b):\n    return a + b\n", "AOR"),
        ("def f(a):\n    return a + 1\n", "AOR"),
        ("def f(a):\n    return a * 2\n", "AOR"),
    ):
        assert all(not v.suspect for _, v in _equiv(src, op))


def test_identical_ast_and_bytecode_detection() -> None:
    src = "def f(a):\n    return a + 1\n"
    m = generate_mutants(src, "m.py", operators=["AOR"])[0]
    same_ast = dataclasses.replace(m, mutated_source=src)
    v = detect_equivalent(src, same_ast)
    assert v.suspect and v.method == "ast"
    # docstring-only difference: ASTs differ, bytecode of the module differs only by docstring const,
    # so it is NOT claimed equivalent by the bytecode check (docstring lives in co_consts)
    doc_src = 'def f(a):\n    "x"\n    return a + 1\n'
    doc = dataclasses.replace(m, mutated_source=doc_src)
    assert detect_equivalent(src, doc).method != "ast"
    # constant folding: different ASTs, identical bytecode
    a = "def f(a):\n    return a + (1 + 1)\n"
    b = "def f(a):\n    return a + 2\n"
    mb = dataclasses.replace(m, mutated_source=b)
    assert detect_equivalent(a, mb).suspect
