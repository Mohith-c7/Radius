"""Domain model of symbol-to-test links (LK-03).

Pure, frozen, deterministically serialisable. Kept inside ``radius_testing.linking``
until LK-05/LK-06 unify link types across the criterion->symbol and
symbol->test sides.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

COMBINE_ALGO_VERSION = "link-combine-v1"
STATIC_ALGO_VERSION = "static-link-v1"
NAMING_ALGO_VERSION = "naming-link-v1"
DYNAMIC_ALGO_VERSION = "dynamic-cov-link-v1"

LINKER_STATIC = "static"
LINKER_NAMING = "naming"
LINKER_DYNAMIC = "dynamic"
LINKER_COMBINED = "combined"
LINKERS = (LINKER_STATIC, LINKER_NAMING, LINKER_DYNAMIC)

MODULE_SYMBOL = "<module>"
MAX_EVIDENCE_PER_LINK = 8


class LinkKind(StrEnum):
    DIRECT_CALL = "direct_call"
    INDIRECT_CALL = "indirect_call"
    IMPORT_REFERENCE = "import_reference"
    NAME_CONVENTION = "name_convention"
    DYNAMIC_COVERAGE = "dynamic_coverage"
    FIXTURE_DEPENDENCY = "fixture_dependency"


_PARAM_SUFFIX = re.compile(r"\[.*\]$", re.DOTALL)


def normalize_test_id(node_id: str) -> str:
    """Return ``path::Class::function`` without a pytest parametrisation suffix.

    ``tests/test_a.py::TestX::test_y[1-2]`` and ``tests/test_a.py::TestX::test_y``
    are the same test for linking: links are per function, the number of cases is
    kept as evidence only. A trailing ``|run``/``|setup`` phase marker is dropped.
    """

    cleaned = node_id.strip().replace("\\", "/")
    if "|" in cleaned and cleaned.rsplit("|", 1)[-1] in {"run", "setup", "teardown"}:
        cleaned = cleaned.rsplit("|", 1)[0]
    return _PARAM_SUFFIX.sub("", cleaned)


def make_test_id(path: str, class_name: str | None, function: str) -> str:
    return "::".join(p for p in (path, class_name, function) if p)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """A changed symbol to find tests for (a projection of LK-01's ``ChangedSymbol``)."""

    symbol_id: str
    path: str
    qualified_name: str
    kind: str = "function"
    language: str = "python"
    new_range: tuple[int, int] | None = None
    old_range: tuple[int, int] | None = None

    @classmethod
    def from_changed_symbol(cls, symbol: Any) -> LinkTarget:
        """Build from an LK-01 ``ChangedSymbol`` (duck-typed; no import needed)."""

        def rng(r: Any) -> tuple[int, int] | None:
            return None if r is None else (int(r.start), int(r.end))

        return cls(
            symbol_id=symbol.symbol_id,
            path=symbol.path,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            language=symbol.language,
            new_range=rng(symbol.new_range),
            old_range=rng(symbol.old_range),
        )

    @property
    def entity_name(self) -> str:
        """Qualified name without ``<locals>`` nesting (nearest addressable ancestor)."""

        return self.qualified_name.split(".<locals>", 1)[0]

    @property
    def simple_name(self) -> str:
        return self.entity_name.rsplit(".", 1)[-1]

    @property
    def class_name(self) -> str | None:
        parts = self.entity_name.split(".")
        return parts[-2] if len(parts) > 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "path": self.path,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "language": self.language,
            "new_range": list(self.new_range) if self.new_range else None,
            "old_range": list(self.old_range) if self.old_range else None,
        }


@dataclass(frozen=True, slots=True)
class LinkComponent:
    """One linker's contribution to a combined link."""

    linker: str
    score: float
    kind: LinkKind
    algo_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "linker": self.linker,
            "score": self.score,
            "kind": self.kind.value,
            "algo_version": self.algo_version,
        }


@dataclass(frozen=True, slots=True)
class SymbolTestLink:
    """Evidence that ``test_id`` can detect a defect in ``symbol_id``."""

    symbol_id: str
    test_id: str
    linker: str
    score: float
    kind: LinkKind
    evidence: tuple[str, ...] = ()
    depth: int | None = None  # call depth for ``indirect_call`` / fixture hops
    algo_version: str = ""
    components: tuple[LinkComponent, ...] = ()  # filled by the combiner
    low_confidence: bool = False  # dynamic-code or name-only candidate

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"link score {self.score} outside [0, 1]")

    @property
    def key(self) -> tuple[str, str]:
        return (self.symbol_id, self.test_id)

    def sort_key(self) -> tuple[Any, ...]:
        return (self.symbol_id, -self.score, self.test_id, self.linker, self.kind.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "test_id": self.test_id,
            "linker": self.linker,
            "score": self.score,
            "kind": self.kind.value,
            "depth": self.depth,
            "evidence": list(self.evidence[:MAX_EVIDENCE_PER_LINK]),
            "algo_version": self.algo_version,
            "low_confidence": self.low_confidence,
            "components": [c.to_dict() for c in self.components],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SymbolTestLink:
        return cls(
            symbol_id=data["symbol_id"],
            test_id=data["test_id"],
            linker=data["linker"],
            score=float(data["score"]),
            kind=LinkKind(data["kind"]),
            evidence=tuple(data.get("evidence", ())),
            depth=data.get("depth"),
            algo_version=data.get("algo_version", ""),
            low_confidence=bool(data.get("low_confidence", False)),
            components=tuple(
                LinkComponent(c["linker"], float(c["score"]), LinkKind(c["kind"]), c["algo_version"])
                for c in data.get("components", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class LinkSet:
    """Links of one linker (or the combiner), deterministically ordered."""

    links: tuple[SymbolTestLink, ...] = ()
    algo_version: str = ""
    notes: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        links: Iterable[SymbolTestLink],
        *,
        algo_version: str,
        notes: Sequence[str] = (),
        config: Mapping[str, Any] | None = None,
    ) -> LinkSet:
        ordered = tuple(sorted(links, key=SymbolTestLink.sort_key))
        return cls(ordered, algo_version, tuple(notes), dict(config or {}))

    def for_symbol(self, symbol_id: str) -> tuple[SymbolTestLink, ...]:
        return tuple(link for link in self.links if link.symbol_id == symbol_id)

    def for_test(self, test_id: str) -> tuple[SymbolTestLink, ...]:
        return tuple(
            sorted(
                (link for link in self.links if link.test_id == test_id),
                key=lambda link: (-link.score, link.symbol_id),
            )
        )

    def tests(self, *, min_score: float = 0.0) -> tuple[str, ...]:
        return tuple(sorted({link.test_id for link in self.links if link.score >= min_score}))

    def by_key(self) -> dict[tuple[str, str], SymbolTestLink]:
        return {link.key: link for link in self.links}

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "notes": list(self.notes),
            "config": self.config,
            "links": [link.to_dict() for link in self.links],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LinkSet:
        return cls(
            tuple(SymbolTestLink.from_dict(d) for d in data.get("links", ())),
            data.get("algo_version", ""),
            tuple(data.get("notes", ())),
            dict(data.get("config", {})),
        )


def is_test_path(path: str) -> bool:
    """pytest/unittest/jest/vitest test file naming (``test*.py``, ``*_test.py``, ``*.test.ts``)."""

    base = path.rsplit("/", 1)[-1]
    if base.endswith(".py"):
        stem = base[:-3]
        return stem.startswith("test") or stem.endswith("_test")
    return bool(re.search(r"\.(test|spec)\.(?:[cm]?[jt]sx?)$", base))
