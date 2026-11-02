"""Mutant generator: operators on hand-written snippets, ids, scope, pragma."""

from __future__ import annotations

import ast
import random

from radius_testing.mutation import OPERATOR_IDS, generate_mutants, mutation_enabled
from radius_testing.mutation.operators import Mutant


def _ops(source: str, **kw) -> set[tuple[str, str]]:
    return {(m.operator, m.replacement) for m in generate_mutants(source, "m.py", **kw)}


def test_flag_default_off() -> None:
    assert mutation_enabled({}) is False
    assert mutation_enabled({"RADIUS_FEATURE_MUTATION": "0"}) is False
    assert mutation_enabled({"RADIUS_FEATURE_MUTATION": "1"}) is True


def test_relational_boundary() -> None:
    got = _ops("def f(a, b):\n    return a < b\n", operators=["ROR"])
    assert got == {("ROR", "return a <= b")}
    got = _ops("def f(a, b):\n    return a >= b\n", operators=["ROR"])
    assert got == {("ROR", "return a > b")}
    assert _ops("def f(a):\n    return a == 1\n", operators=["ROR"]) == {("ROR", "return a != 1")}
    assert _ops("def f(a, b):\n    return a in b\n", operators=["ROR"]) == {
        ("ROR", "return a not in b")
    }


def test_arithmetic() -> None:
    assert _ops("def f(a, b):\n    return a + b\n", operators=["AOR"]) == {("AOR", "return a - b")}
    assert _ops("def f(a, b):\n    return a * b\n", operators=["AOR"]) == {("AOR", "return a / b")}
    assert _ops("def f(a):\n    a += 1\n    return a\n", operators=["AOR"]) == {("AOR", "a -= 1")}


def test_boolean_and_condition_removal() -> None:
    src = "def f(a, b):\n    return a and b\n"
    assert _ops(src, operators=["BOOL"]) == {("BOOL", "return a or b")}
    assert _ops(src, operators=["CRM"]) == {("CRM", "return b"), ("CRM", "return a")}


def test_negation() -> None:
    assert _ops("def f(a):\n    return not a\n", operators=["NEG"]) == {("NEG", "return a")}
    got = _ops("def f(a):\n    if a:\n        return 1\n    return 2\n", operators=["NEG", "CRM"])
    assert ("NEG", "if not a:") in got
    assert ("CRM", "if False:") in got


def test_constants() -> None:
    got = _ops("def f():\n    return 0\n", operators=["CON"])
    assert got == {("CON", "return 1")}
    got = _ops("def f():\n    return True\n", operators=["CON"])
    assert got == {("CON", "return False")}
    got = _ops("def f():\n    return 'a'\n", operators=["CON"])
    assert got == {("CON", "return 'XXa'")}


def test_return_raise_call_args() -> None:
    assert _ops("def f(a):\n    return a\n", operators=["RET"]) == {("RET", "return None")}
    assert _ops("def f():\n    return None\n", operators=["RET"]) == set()
    assert _ops("def f():\n    raise ValueError()\n", operators=["EXC"]) == {("EXC", "pass")}
    assert _ops("def f(x):\n    g(x)\n", operators=["CALL"]) == {("CALL", "pass")}
    assert _ops("def f(a, b):\n    return h(a, b)\n", operators=["ARG"]) == {
        ("ARG", "return h(b, a)")
    }
    # a single argument cannot be swapped; a starred leading argument is skipped
    assert _ops("def f(a):\n    return h(a)\n", operators=["ARG"]) == set()
    assert _ops("def f(a, b):\n    return h(*a, b)\n", operators=["ARG"]) == set()


def test_all_mutants_are_valid_distinct_python() -> None:
    src = "def f(a, b):\n    if a < b and b:\n        return a + 1\n    raise ValueError('x')\n"
    baseline = ast.unparse(ast.parse(src))
    mutants = generate_mutants(src, "m.py")
    assert mutants
    assert {m.operator for m in mutants} <= set(OPERATOR_IDS)
    for m in mutants:
        ast.parse(m.mutated_source)
        assert m.mutated_source != baseline
    assert len({m.id for m in mutants}) == len(mutants)


def test_deterministic_ids_and_order() -> None:
    src = "def f(a, b):\n    if a < b:\n        return a - b\n    return b\n"
    a = generate_mutants(src, "m.py")
    b = generate_mutants(src, "m.py")
    assert [m.id for m in a] == [m.id for m in b]
    keys = [(m.path, m.lineno, m.col, m.operator, m.replacement, m.id) for m in a]
    assert keys == sorted(keys)
    shuffled = list(a)
    random.Random(1).shuffle(shuffled)
    assert sorted(shuffled, key=lambda m: (m.lineno, m.col, m.operator, m.replacement, m.id)) == a
    # the path is part of the identity; the same code elsewhere has different ids
    other = generate_mutants(src, "n.py")
    assert {m.id for m in a}.isdisjoint({m.id for m in other})


def test_position_tracking_and_symbol() -> None:
    src = "class C:\n    def m(self, x):\n        return x > 3\n\n\ndef top(y):\n    return y + 1\n"
    by = {m.operator + str(m.lineno): m for m in generate_mutants(src, "m.py", operators=["ROR", "AOR"])}
    ror = by["ROR3"]
    assert (ror.lineno, ror.col, ror.end_col) == (3, 15, 20)
    assert ror.original == "x > 3" and ror.symbol == "C.m"
    assert by["AOR7"].symbol == "top"


def test_scope_limits_to_line_ranges() -> None:
    src = "def f(a):\n    return a + 1\n\n\ndef g(a):\n    return a + 2\n"
    both = generate_mutants(src, "m.py", operators=["AOR"])
    assert {m.symbol for m in both} == {"f", "g"}
    only_g = generate_mutants(src, "m.py", scope=[(5, 6)], operators=["AOR"])
    assert {m.symbol for m in only_g} == {"g"}
    assert generate_mutants(src, "m.py", scope=[], operators=["AOR"]) == []


def test_pragma_no_mutate_skips_line() -> None:
    src = "def f(a):\n    x = a + 1  # pragma: no mutate\n    return a - x\n"
    got = generate_mutants(src, "m.py", operators=["AOR"])
    assert [m.lineno for m in got] == [3]


def test_docstrings_and_fstrings_not_mutated() -> None:
    src = 'def f(a):\n    """Doc 1."""\n    return f"v={a} items"\n'
    assert [m for m in generate_mutants(src, "m.py", operators=["CON"])] == []


def test_unparseable_source_yields_nothing() -> None:
    assert generate_mutants("def (:", "m.py") == []


def test_mutant_is_immutable_value() -> None:
    m = generate_mutants("def f(a):\n    return a + 1\n", "m.py", operators=["AOR"])[0]
    assert isinstance(m, Mutant)
    assert m.to_dict()["operator"] == "AOR"


def test_callx_is_opt_in_and_replaces_call_by_operand() -> None:
    src = "def f(a):\n    return a.strip().lower()\n"
    assert not any(m.operator == "CALLX" for m in generate_mutants(src, "m.py"))
    got = _ops(src, operators=["CALLX"])
    assert got == {("CALLX", "return a.strip()"), ("CALLX", "return a.lower()")}
    assert _ops("def f(a):\n    return len(a)\n", operators=["CALLX"]) == {("CALLX", "return a")}
    # statement calls belong to CALL; calls with arguments or keywords are left alone
    assert _ops("def f(a):\n    g(a)\n", operators=["CALLX"]) == set()
    assert _ops("def f(a):\n    return a.split(',')\n", operators=["CALLX"]) == set()
