"""Domain types of criterion -> test relevance (VS-04, ``r_ct``).

Plain, frozen, JSON-serialisable data. ``radius_linking`` never imports
``radius_testing``: the assertions of a test enter through :class:`AssertionFact`
(a code-free summary of what one assertion checks), which an adapter builds from an
LK-04 ``AssertionRecord`` (``AssertionFact.from_assertion_dict`` reads its
``to_dict()`` shape) or from any other source.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

RELEVANCE_ALGO_VERSION = "criterion-test-relevance-v1"

# Reason codes (``RelevanceReason.code``).
R_HINT = "explicit_hint"
R_LEXICAL = "lexical_overlap"
R_ASSERTION = "assertion_subject"
R_EXCEPTION = "exception_match"
R_NAME = "name_convention"
R_SPECIFICITY = "specificity_penalty"
R_BEHAVIOR = "behavior_mismatch"
R_EXC_TYPE = "exception_type_mismatch"
R_OTHER_SYMBOLS = "asserts_other_symbols"
R_NO_SIGNAL = "no_signal"
R_BELOW_FLOOR = "below_floor"

REASON_CODES = (
    R_HINT,
    R_LEXICAL,
    R_ASSERTION,
    R_EXCEPTION,
    R_NAME,
    R_SPECIFICITY,
    R_BEHAVIOR,
    R_EXC_TYPE,
    R_OTHER_SYMBOLS,
    R_NO_SIGNAL,
    R_BELOW_FLOOR,
)

_DIGITS = 6


def _r(value: float) -> float:
    return round(value, _DIGITS)


@dataclass(frozen=True, slots=True)
class AssertionFact:
    """What one assertion of a test checks (no source code).

    ``subject`` is the asserted expression text, ``expected`` the right-hand side
    text, ``kind`` the assertion kind (LK-04 values such as ``equality`` or
    ``exception``), ``symbol_names`` the names of the callables/attributes the
    subject refers to, ``exception_type`` the expected exception type (for
    ``kind == "exception"``).
    """

    subject: str = ""
    expected: str = ""
    kind: str = ""
    symbol_names: tuple[str, ...] = ()
    exception_type: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_names", tuple(self.symbol_names))

    @property
    def is_exception(self) -> bool:
        return self.kind == "exception" or bool(self.exception_type)

    @classmethod
    def from_assertion_dict(cls, data: Mapping[str, Any]) -> AssertionFact:
        """Adapt the ``to_dict()`` shape of an LK-04 ``AssertionRecord`` (plain data)."""

        subject = data.get("subject") or {}
        expected = data.get("expected") or {}
        kind = str(data.get("kind", ""))
        exp_text = str(expected.get("text", ""))
        refs = tuple(
            str(r.get("name", "")) for r in subject.get("refs", ()) if r.get("name")
        )
        exc = (
            exp_text
            if (kind == "exception" or expected.get("form") == "exception_type")
            else ""
        )
        return cls(str(subject.get("text", "")), exp_text, kind, refs, exc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "expected": self.expected,
            "kind": self.kind,
            "symbol_names": list(self.symbol_names),
            "exception_type": self.exception_type,
        }


@dataclass(frozen=True, slots=True)
class TestDoc:
    """A test and the text/assertion facts relevance is judged on."""

    __test__ = False  # not a pytest class

    test_id: str
    name: str
    docstring: str = ""
    param_ids: tuple[str, ...] = ()
    assertions: tuple[AssertionFact, ...] = ()
    literals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "param_ids", tuple(self.param_ids))
        object.__setattr__(self, "assertions", tuple(self.assertions))
        object.__setattr__(self, "literals", tuple(self.literals))


class TestDocPort(Protocol):
    """Source of :class:`TestDoc` (an adapter over LK-04 assertions and test sources)."""

    __test__ = False

    def test_docs(self) -> Sequence[TestDoc]: ...


@dataclass(frozen=True, slots=True)
class RelevanceReason:
    """One explainable step. ``value`` is the signal score (or the factor for penalties)."""

    code: str
    detail: str
    value: float

    def __post_init__(self) -> None:
        if math.isnan(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("RelevanceReason value must be in [0, 1].")
        object.__setattr__(self, "value", _r(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RelevanceReason:
        return cls(data["code"], data["detail"], float(data["value"]))


@dataclass(frozen=True, slots=True)
class CriterionTestRelevance:
    """``r_ct``: how relevant ``test_id`` is to ``criterion_id`` (0.0 = no credit)."""

    criterion_id: str
    test_id: str
    r_ct: float
    reasons: tuple[RelevanceReason, ...] = ()
    symbol_ids: tuple[str, ...] = ()
    rank: int = 0

    def __post_init__(self) -> None:
        if math.isnan(self.r_ct) or not 0.0 <= self.r_ct <= 1.0:
            raise ValueError("r_ct must be in [0, 1].")
        object.__setattr__(self, "r_ct", _r(self.r_ct))
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "symbol_ids", tuple(self.symbol_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "test_id": self.test_id,
            "r_ct": self.r_ct,
            "rank": self.rank,
            "symbol_ids": list(self.symbol_ids),
            "reasons": [r.to_dict() for r in self.reasons],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CriterionTestRelevance:
        return cls(
            data["criterion_id"],
            data["test_id"],
            float(data["r_ct"]),
            tuple(RelevanceReason.from_dict(r) for r in data.get("reasons", ())),
            tuple(data.get("symbol_ids", ())),
            int(data.get("rank", 0)),
        )


@dataclass(frozen=True, slots=True)
class RelevanceSet:
    """All scored pairs, ordered by ``(criterion_id, rank)``; ``config`` records constants."""

    items: tuple[CriterionTestRelevance, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    algo_version: str = RELEVANCE_ALGO_VERSION

    def for_criterion(self, criterion_id: str) -> tuple[CriterionTestRelevance, ...]:
        return tuple(i for i in self.items if i.criterion_id == criterion_id)

    def get(self, criterion_id: str, test_id: str) -> CriterionTestRelevance | None:
        for i in self.items:
            if i.criterion_id == criterion_id and i.test_id == test_id:
                return i
        return None

    def r_ct(self, criterion_id: str, test_id: str) -> float:
        item = self.get(criterion_id, test_id)
        return item.r_ct if item else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "config": dict(self.config),
            "items": [i.to_dict() for i in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> RelevanceSet:
        data = json.loads(text)
        return cls(
            tuple(CriterionTestRelevance.from_dict(i) for i in data["items"]),
            dict(data.get("config", {})),
            data.get("algo_version", RELEVANCE_ALGO_VERSION),
        )
