"""Domain model of extracted test assertions (LK-04).

Frozen, deterministically serialisable records. This module computes **no**
assertion-strength score: it only exposes ``StrengthFeatures`` that EV-06 turns
into ``a_static``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ALGO_VERSION = "assertion-extract-v1"


class AssertionKind(StrEnum):
    EQUALITY = "equality"  # ==, !=, assertEqual, toBe, toEqual
    COMPARISON = "comparison"  # <, <=, >, >= (also chains)
    APPROX = "approx"  # pytest.approx, math.isclose, assertAlmostEqual, toBeCloseTo
    MEMBERSHIP = "membership"  # in / not in, assertIn, toContain
    IDENTITY = "identity"  # is / is not (not None)
    NONE_CHECK = "none_check"  # is None / is not None / assertIsNone
    TRUTHINESS = "truthiness"  # assert x / assert not x / assertTrue
    TYPE_CHECK = "type_check"  # isinstance
    LENGTH = "length"  # len(x) == n
    REGEX = "regex"  # assertRegex, toMatch, re.match(...)
    QUANTIFIED = "quantified"  # all(...) / any(...)
    DISJUNCTION = "disjunction"  # a or b
    EXCEPTION = "exception"  # pytest.raises, assertRaises, toThrow
    WARNING = "warning"  # pytest.warns, assertWarns
    MOCK_CALL = "mock_call"  # assert_called_with, call_args, toHaveBeenCalledWith
    SNAPSHOT = "snapshot"  # syrupy, approvaltests, regression fixtures, toMatchSnapshot
    UNKNOWN_ASSERT = "unknown_assert"  # custom ``assert_*`` helper that could not be followed


class Exactness(StrEnum):
    """How tightly the assertion pins the observed value (coarse)."""

    EXACT = "exact"  # equality with a value / expression
    APPROX = "approx"
    MEMBERSHIP = "membership"
    ORDERING = "ordering"
    PATTERN = "pattern"  # regex
    TRUTHINESS = "truthiness"
    NONE_ONLY = "none_only"
    TYPE_ONLY = "type_only"
    LENGTH_ONLY = "length_only"
    IDENTITY = "identity"
    EXCEPTION = "exception"
    CALL_ONLY = "call_only"  # mock was (not) called
    CALL_ARGS = "call_args"  # mock called with specific args
    SNAPSHOT = "snapshot"
    DISJUNCTION = "disjunction"
    NONE = "none"  # dead / unknown


class ExceptionSpecificity(StrEnum):
    NONE = "none"  # not an exception assertion / type not statically known
    BROAD = "broad"  # Exception / BaseException
    SPECIFIC = "specific"
    SPECIFIC_MATCH = "specific_match"  # specific type plus ``match=``/message check


class Dependence(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SymbolRef:
    """A symbol-like name referenced by an assertion subject."""

    name: str  # dotted name as written (after local data flow), e.g. ``calc.add``
    qualified: str | None = None  # import-qualified, e.g. ``pkg.calc.add``
    symbol_ids: tuple[str, ...] = ()  # filled by a ``SymbolResolver``
    role: str = "call"  # call | attribute

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified": self.qualified,
            "symbol_ids": list(self.symbol_ids),
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class Expected:
    """The right-hand / expected side of an assertion."""

    text: str = ""
    form: str = "none"  # none | literal | expression | pattern | snapshot | exception_type
    literal_kind: str | None = None  # bool | none | int | float | str | bytes | collection | other
    complexity: int = 0  # 0 none, 1 trivial (True/None/0/""/[]), 2 simple literal, 3 rich literal

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "form": self.form,
            "literal_kind": self.literal_kind,
            "complexity": self.complexity,
        }


@dataclass(frozen=True, slots=True)
class StrengthFeatures:
    """Inputs for EV-06. Raw features only; no score."""

    exactness: Exactness = Exactness.NONE
    value_specificity: int = 0  # = Expected.complexity (0..3)
    distinct_subject_symbols: int = 0
    edge_inputs: bool | None = None  # nearby parametrize/call literals include None/0/""/[]/negative
    edge_input_source: str | None = None  # parametrize | call_args | None
    exception_specificity: ExceptionSpecificity = ExceptionSpecificity.NONE
    exception_match: bool = False  # ``match=`` / regex variant present
    exception_inspected: bool = False  # the ``as`` exception object is asserted on later
    exception_block_size: int | None = None  # statements in the ``with raises`` block
    tolerance_rel: float | None = None
    tolerance_abs: float | None = None
    depends_on_changed: Dependence = Dependence.UNKNOWN
    circular: bool = False  # expected computed by the same callee as the subject
    mock_only: bool = False  # subject derives only from a Mock created in the test
    mock_origin: str | None = None  # created | patched | param
    in_loop: bool = False
    in_parametrized: bool = False
    property_based: bool = False  # hypothesis
    swallowed: bool = False  # inside try/except that catches AssertionError
    dead: bool = False
    dead_reason: str | None = None  # constant_true | constant_false | tautology | literal_comparison
    negated: bool = False
    quantifier: str | None = None  # all | any
    snapshot_library: str | None = None
    helper_depth: int = 0  # 0 = in the test body, 1..2 = via helpers

    def to_dict(self) -> dict[str, Any]:
        return {
            "exactness": self.exactness.value,
            "value_specificity": self.value_specificity,
            "distinct_subject_symbols": self.distinct_subject_symbols,
            "edge_inputs": self.edge_inputs,
            "edge_input_source": self.edge_input_source,
            "exception_specificity": self.exception_specificity.value,
            "exception_match": self.exception_match,
            "exception_inspected": self.exception_inspected,
            "exception_block_size": self.exception_block_size,
            "tolerance_rel": self.tolerance_rel,
            "tolerance_abs": self.tolerance_abs,
            "depends_on_changed": self.depends_on_changed.value,
            "circular": self.circular,
            "mock_only": self.mock_only,
            "mock_origin": self.mock_origin,
            "in_loop": self.in_loop,
            "in_parametrized": self.in_parametrized,
            "property_based": self.property_based,
            "swallowed": self.swallowed,
            "dead": self.dead,
            "dead_reason": self.dead_reason,
            "negated": self.negated,
            "quantifier": self.quantifier,
            "snapshot_library": self.snapshot_library,
            "helper_depth": self.helper_depth,
        }


@dataclass(frozen=True, slots=True)
class Location:
    path: str
    line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "end_line": self.end_line}


@dataclass(frozen=True, slots=True)
class AssertionRecord:
    test_id: str
    kind: AssertionKind
    subject_text: str
    subject_refs: tuple[SymbolRef, ...]
    expected: Expected
    comparator: str
    strength_features: StrengthFeatures
    location: Location
    framework: str  # pytest | unittest | mock | hypothesis | snapshot | jest | vitest | node-assert
    confidence: float
    via: tuple[str, ...] = ()  # helper call chain, ``name@line``
    algo_version: str = ALGO_VERSION
    col: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} outside [0, 1]")

    @property
    def assertion_id(self) -> str:
        """Deterministic id: hash of test, location, call chain, kind and subject text."""

        raw = "\x1f".join(
            [
                self.test_id,
                self.location.path,
                str(self.location.line),
                str(self.col),
                ",".join(self.via),
                self.kind.value,
                self.comparator,
                self.subject_text,
                self.expected.text,
            ]
        )
        return "as_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def sort_key(self) -> tuple[Any, ...]:
        return (self.test_id, self.location.path, self.location.line, self.col, self.via, self.kind.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "test_id": self.test_id,
            "kind": self.kind.value,
            "subject": {"text": self.subject_text, "refs": [r.to_dict() for r in self.subject_refs]},
            "expected": self.expected.to_dict(),
            "comparator": self.comparator,
            "strength_features": self.strength_features.to_dict(),
            "location": self.location.to_dict(),
            "framework": self.framework,
            "confidence": self.confidence,
            "via": list(self.via),
            "algo_version": self.algo_version,
        }


@dataclass(frozen=True, slots=True)
class TestSummary:
    """Per-test facts that are not tied to one assertion."""

    __test__ = False  # not a pytest class

    test_id: str
    path: str
    line: int
    language: str
    assertion_count: int = 0
    has_assertions: bool = False
    property_based: bool = False
    parametrized: bool = False
    case_count: int | None = None  # literal parametrize cases when statically known
    has_dynamic_assertions: bool = False  # e.g. unresolved ``assert_*`` calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "path": self.path,
            "line": self.line,
            "language": self.language,
            "assertion_count": self.assertion_count,
            "has_assertions": self.has_assertions,
            "property_based": self.property_based,
            "parametrized": self.parametrized,
            "case_count": self.case_count,
            "has_dynamic_assertions": self.has_dynamic_assertions,
        }


@dataclass(frozen=True, slots=True)
class AssertionSet:
    """All assertions of a set of test files, canonically ordered."""

    assertions: tuple[AssertionRecord, ...] = ()
    tests: tuple[TestSummary, ...] = ()
    notes: tuple[str, ...] = ()  # unparseable files, truncation, partial-language warnings
    algo_version: str = ALGO_VERSION

    @property
    def tests_without_assertions(self) -> tuple[str, ...]:
        return tuple(t.test_id for t in self.tests if not t.has_assertions)

    def for_test(self, test_id: str) -> tuple[AssertionRecord, ...]:
        return tuple(a for a in self.assertions if a.test_id == test_id)

    def by_test(self) -> dict[str, tuple[AssertionRecord, ...]]:
        out: dict[str, list[AssertionRecord]] = {}
        for a in self.assertions:
            out.setdefault(a.test_id, []).append(a)
        return {k: tuple(v) for k, v in out.items()}

    def counts(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for a in self.assertions:
            kinds[a.kind.value] = kinds.get(a.kind.value, 0) + 1
        sf = [a.strength_features for a in self.assertions]
        return {
            "tests": len(self.tests),
            "assertions": len(self.assertions),
            "tests_without_assertions": len(self.tests_without_assertions),
            "by_kind": dict(sorted(kinds.items())),
            "dead": sum(1 for f in sf if f.dead),
            "mock_only": sum(1 for f in sf if f.mock_only),
            "circular": sum(1 for f in sf if f.circular),
            "in_loop": sum(1 for f in sf if f.in_loop),
            "swallowed": sum(1 for f in sf if f.swallowed),
            "via_helper": sum(1 for f in sf if f.helper_depth > 0),
            "snapshot": sum(1 for a in self.assertions if a.kind is AssertionKind.SNAPSHOT),
            "property_based_tests": sum(1 for t in self.tests if t.property_based),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "counts": self.counts(),
            "notes": list(self.notes),
            "tests": [t.to_dict() for t in self.tests],
            "assertions": [a.to_dict() for a in self.assertions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)


def canonical(records: Iterable[AssertionRecord]) -> tuple[AssertionRecord, ...]:
    """Sort and de-duplicate by ``assertion_id``."""

    seen: dict[str, AssertionRecord] = {}
    for r in records:
        seen.setdefault(r.assertion_id, r)
    return tuple(sorted(seen.values(), key=lambda r: (r.sort_key(), r.assertion_id)))
