"""Pure domain model of criterion -> symbol linking (LK-02).

Frozen dataclasses with deterministic ``to_dict`` / ``from_dict`` so a
:class:`LinkSet` can be stored (LK-05), hashed and compared across runs. No
parsing, I/O, logging or customer data lives here: every input is plain data
and the same inputs always give the same output.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

ALGO_VERSION = "criterion-symbol-links-v1"
COMBINED = "combined"

LINKER_EXPLICIT = "explicit"
LINKER_LEXICAL = "lexical"
LINKER_IDENTIFIER = "identifier"
LINKER_STRUCTURAL = "structural"
LINKER_CHANGE_PRIOR = "change_prior"
LINKER_RERANK = "rerank"

_SCORE_DIGITS = 6


def clamp01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return min(1.0, max(0.0, value))


def _r(value: float) -> float:
    return round(value, _SCORE_DIGITS)


@dataclass(frozen=True, slots=True)
class Reason:
    """Why a linker produced (part of) a score. ``score`` is that part, in [0, 1]."""

    linker: str
    kind: str
    detail: str
    score: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:  # also rejects NaN
            raise ValueError("Reason score must be in [0, 1].")
        object.__setattr__(self, "score", _r(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "linker": self.linker,
            "kind": self.kind,
            "detail": self.detail,
            "score": _r(self.score),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reason:
        return cls(data["linker"], data["kind"], data["detail"], float(data["score"]))


@dataclass(frozen=True, slots=True)
class Link:
    """A scored edge from one criterion to one changed symbol.

    ``linker`` is the producing linker's name, or ``"combined"`` for the final
    ranked edge. ``rank`` is 1-based within (criterion, linker); 0 = unranked.
    """

    criterion_id: str
    symbol_id: str
    linker: str
    score: float
    evidence: tuple[Reason, ...] = ()
    rank: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("Link score must be in [0, 1].")
        object.__setattr__(self, "score", _r(self.score))
        if self.rank < 0:
            raise ValueError("Link rank must be >= 0.")
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def with_rank(self, rank: int) -> Link:
        return Link(
            self.criterion_id,
            self.symbol_id,
            self.linker,
            self.score,
            self.evidence,
            rank,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "symbol_id": self.symbol_id,
            "linker": self.linker,
            "score": _r(self.score),
            "rank": self.rank,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Link:
        return cls(
            criterion_id=data["criterion_id"],
            symbol_id=data["symbol_id"],
            linker=data["linker"],
            score=float(data["score"]),
            rank=int(data.get("rank", 0)),
            evidence=tuple(Reason.from_dict(e) for e in data.get("evidence", [])),
        )


def link_sort_key(link: Link) -> tuple[Any, ...]:
    """Deterministic order: criterion, linker, score desc, symbol id."""

    return (
        link.criterion_id,
        link.linker,
        -round(link.score, _SCORE_DIGITS),
        link.symbol_id,
    )


@dataclass(frozen=True, slots=True)
class CriterionInput:
    """What the linkers need to know about a criterion (decoupled from ``radius_intent``).

    ``paths`` / ``tests`` are the author hints from ``.radius/intent.yml``;
    ``rationale`` is the testability rationale; ``weight`` is the criterion weight.
    """

    criterion_id: str
    text: str
    rationale: str | None = None
    paths: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    weight: float = 1.0
    state: str = "proposed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "tests", tuple(self.tests))

    @property
    def full_text(self) -> str:
        return f"{self.text}\n{self.rationale}" if self.rationale else self.text


@dataclass(frozen=True, slots=True)
class SymbolDoc:
    """A changed symbol plus the text the linkers search (its "document").

    ``ref`` (``path::qualified_name``) is the form used by the benchmark gold
    links in ``expected.json``.
    """

    symbol_id: str
    path: str
    qualified_name: str
    kind: str = "function"
    language: str = ""
    change_kind: str = "modified_body"
    is_behavioral: bool = True
    signature: str = ""
    docstring: str = ""
    comments: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    is_test: bool = False

    @property
    def ref(self) -> str:
        return f"{self.path}::{self.qualified_name}"

    @property
    def simple_name(self) -> str:
        return self.qualified_name.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class LinkSet:
    """All links of one analysis: one intent snapshot against one change set.

    ``links`` are the final, combined, ranked edges (``linker == "combined"``);
    ``by_linker`` keeps every linker's own edges and reasons for ablation and
    explanation. Both are in deterministic order. ``algo_versions`` maps each
    component (linkers, combiner, optional reranker) to its version string.
    """

    snapshot_id: str
    changeset_ref: str
    links: tuple[Link, ...] = ()
    by_linker: tuple[Link, ...] = ()
    algo_versions: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    algo_version: str = ALGO_VERSION

    def for_criterion(self, criterion_id: str) -> tuple[Link, ...]:
        return tuple(link for link in self.links if link.criterion_id == criterion_id)

    def top(self, criterion_id: str, k: int = 1) -> tuple[Link, ...]:
        return self.for_criterion(criterion_id)[:k]

    def ranking(self, criterion_id: str, linker: str = COMBINED) -> list[str]:
        """Symbol ids for ``criterion_id`` in rank order for ``linker``."""

        pool = self.links if linker == COMBINED else self.by_linker
        mine = [
            link
            for link in pool
            if link.criterion_id == criterion_id and link.linker == linker
        ]
        return [
            link.symbol_id
            for link in sorted(
                mine, key=lambda link: (link.rank or 10**9, link.symbol_id)
            )
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "snapshot_id": self.snapshot_id,
            "changeset_ref": self.changeset_ref,
            "algo_versions": dict(sorted(self.algo_versions.items())),
            "config": self.config,
            "diagnostics": list(self.diagnostics),
            "links": [x.to_dict() for x in self.links],
            "by_linker": [x.to_dict() for x in self.by_linker],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LinkSet:
        return cls(
            algo_version=data.get("algo_version", ALGO_VERSION),
            snapshot_id=data["snapshot_id"],
            changeset_ref=data["changeset_ref"],
            algo_versions=dict(data.get("algo_versions", {})),
            config=dict(data.get("config", {})),
            diagnostics=tuple(data.get("diagnostics", [])),
            links=tuple(Link.from_dict(x) for x in data.get("links", [])),
            by_linker=tuple(Link.from_dict(x) for x in data.get("by_linker", [])),
        )

    @classmethod
    def from_json(cls, text: str) -> LinkSet:
        return cls.from_dict(json.loads(text))
