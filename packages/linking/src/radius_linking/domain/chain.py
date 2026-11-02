"""Criterion -> symbol -> test chain model (LK-06).

Unifies the two link families into one chain. ``radius_linking`` must not import
``radius_testing``, so the symbol -> test hop is a small plain-data port,
:class:`SymbolTestEdge`; the composition layer converts an LK-03
``radius_testing.linking.SymbolTestLink`` with :meth:`SymbolTestEdge.from_object`
(duck typed: ``symbol_id``, ``test_id``, ``score``, ``kind``, optional ``linker``,
``low_confidence``, ``evidence``, ``components``).

Everything is frozen, deterministically ordered and JSON round-trippable. The
confidence values here are **uncalibrated** unless ``score_kind`` says otherwise.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from radius_linking.domain.model import Link, Reason, clamp01

CHAIN_ALGO_VERSION = "link-chain-v1"
SCORE_KIND_UNCALIBRATED = "link_confidence_uncalibrated"
SCORE_KIND_CALIBRATED = "link_confidence_calibrated"

KIND_DYNAMIC_COVERAGE = "dynamic_coverage"
LINKER_CHAIN = "chain"

# Test outcome labels accepted by the combiner (anything else is "unknown").
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_FLAKY = "flaky"
STATUS_SKIPPED = "skipped"
STATUS_UNKNOWN = "unknown"

# Why a criterion has no chain (``CriterionSupportLinks.unlinked_reason``).
UNLINKED_NO_SYMBOL = "no_symbol_candidates"
UNLINKED_NON_BEHAVIORAL = "only_non_behavioral_symbols"
UNLINKED_UNTESTED = "untested_change"
UNLINKED_TESTS_WITHOUT_SYMBOL = "tests_without_symbol"
UNLINKED_WEAK = "only_weak_chains"

_DIGITS = 6


def _r(value: float) -> float:
    return round(value, _DIGITS)


@dataclass(frozen=True, slots=True)
class SymbolTestEdge:
    """Plain-data view of one symbol -> test link (LK-03 ``SymbolTestLink``)."""

    symbol_id: str
    test_id: str
    score: float
    kind: str = "static"
    linker: str = "combined"
    low_confidence: bool = False
    evidence: tuple[str, ...] = ()
    components: tuple[tuple[str, float], ...] = ()  # (linker, score) of the inputs

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("SymbolTestEdge score must be in [0, 1].")
        object.__setattr__(self, "score", _r(self.score))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "components", tuple(self.components))

    @classmethod
    def from_object(cls, link: Any) -> SymbolTestEdge:
        kind = getattr(link, "kind", "static")
        comps = tuple(
            (str(c.linker), float(c.score)) for c in getattr(link, "components", ())
        )
        return cls(
            symbol_id=link.symbol_id,
            test_id=link.test_id,
            score=float(link.score),
            kind=str(getattr(kind, "value", kind)),
            linker=str(getattr(link, "linker", "combined")),
            low_confidence=bool(getattr(link, "low_confidence", False)),
            evidence=tuple(getattr(link, "evidence", ()))[:8],
            components=comps,
        )

    @property
    def is_dynamic(self) -> bool:
        return self.kind == KIND_DYNAMIC_COVERAGE or any(
            name == "dynamic" for name, _ in self.components
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "test_id": self.test_id,
            "score": self.score,
            "kind": self.kind,
            "linker": self.linker,
            "low_confidence": self.low_confidence,
            "evidence": list(self.evidence),
            "components": [[n, _r(s)] for n, s in self.components],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SymbolTestEdge:
        return cls(
            symbol_id=data["symbol_id"],
            test_id=data["test_id"],
            score=float(data["score"]),
            kind=data.get("kind", "static"),
            linker=data.get("linker", "combined"),
            low_confidence=bool(data.get("low_confidence", False)),
            evidence=tuple(data.get("evidence", ())),
            components=tuple((n, float(s)) for n, s in data.get("components", ())),
        )


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One criterion -> symbol -> test chain with an explained score.

    ``chain_score`` is the value consumers should use; ``raw_chain_score`` is the
    uncalibrated value (equal unless a calibrator was applied). ``specificity`` in
    (0, 1] is the cross-criterion penalty for tests that cover many criteria;
    ``support_score = raw_chain_score * specificity`` is what the per-criterion
    aggregation uses.
    """

    criterion_id: str
    symbol_id: str
    test_id: str
    c2s: Link
    s2t: SymbolTestEdge
    chain_score: float
    reasons: tuple[Reason, ...] = ()
    raw_chain_score: float | None = None
    specificity: float = 1.0
    test_status: str = STATUS_UNKNOWN
    score_kind: str = SCORE_KIND_UNCALIBRATED

    def __post_init__(self) -> None:
        if not 0.0 <= self.chain_score <= 1.0:
            raise ValueError("chain_score must be in [0, 1].")
        if not 0.0 < self.specificity <= 1.0:
            raise ValueError("specificity must be in (0, 1].")
        object.__setattr__(self, "chain_score", _r(self.chain_score))
        raw = self.chain_score if self.raw_chain_score is None else self.raw_chain_score
        object.__setattr__(self, "raw_chain_score", _r(clamp01(raw)))
        object.__setattr__(self, "specificity", _r(self.specificity))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    @property
    def support_score(self) -> float:
        return _r((self.raw_chain_score or 0.0) * self.specificity)

    def sort_key(self) -> tuple[Any, ...]:
        return (-self.support_score, self.symbol_id, self.test_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "symbol_id": self.symbol_id,
            "test_id": self.test_id,
            "chain_score": self.chain_score,
            "raw_chain_score": self.raw_chain_score,
            "specificity": self.specificity,
            "test_status": self.test_status,
            "score_kind": self.score_kind,
            "c2s": self.c2s.to_dict(),
            "s2t": self.s2t.to_dict(),
            "reasons": [r.to_dict() for r in self.reasons],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChainLink:
        return cls(
            criterion_id=data["criterion_id"],
            symbol_id=data["symbol_id"],
            test_id=data["test_id"],
            c2s=Link.from_dict(data["c2s"]),
            s2t=SymbolTestEdge.from_dict(data["s2t"]),
            chain_score=float(data["chain_score"]),
            raw_chain_score=float(data["raw_chain_score"]),
            specificity=float(data.get("specificity", 1.0)),
            test_status=data.get("test_status", STATUS_UNKNOWN),
            score_kind=data.get("score_kind", SCORE_KIND_UNCALIBRATED),
            reasons=tuple(Reason.from_dict(r) for r in data.get("reasons", ())),
        )


@dataclass(frozen=True, slots=True)
class CriterionSupportLinks:
    """All chains of one criterion plus its overall link confidence.

    ``link_confidence`` is "how sure are we that real, relevant tests are wired
    to this criterion's code", in [0, 1]. It is *not* test quality and not a
    verdict; the verdict layer multiplies by evidence quality (DESIGN 6.3/6.4).
    ``unlinked_reason`` is set exactly when there is no counted chain.
    """

    criterion_id: str
    chains: tuple[ChainLink, ...] = ()
    link_confidence: float = 0.0
    unlinked_reason: str | None = None
    reasons: tuple[Reason, ...] = ()
    raw_link_confidence: float | None = None
    score_kind: str = SCORE_KIND_UNCALIBRATED
    suspicious: bool = False
    algo_version: str = CHAIN_ALGO_VERSION

    def __post_init__(self) -> None:
        if not 0.0 <= self.link_confidence <= 1.0:
            raise ValueError("link_confidence must be in [0, 1].")
        object.__setattr__(self, "link_confidence", _r(self.link_confidence))
        raw = (
            self.link_confidence
            if self.raw_link_confidence is None
            else self.raw_link_confidence
        )
        object.__setattr__(self, "raw_link_confidence", _r(clamp01(raw)))
        object.__setattr__(self, "chains", tuple(self.chains))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    @property
    def best(self) -> ChainLink | None:
        return self.chains[0] if self.chains else None

    @property
    def test_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.test_id for c in self.chains))

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "link_confidence": self.link_confidence,
            "raw_link_confidence": self.raw_link_confidence,
            "score_kind": self.score_kind,
            "unlinked_reason": self.unlinked_reason,
            "suspicious": self.suspicious,
            "algo_version": self.algo_version,
            "reasons": [r.to_dict() for r in self.reasons],
            "chains": [c.to_dict() for c in self.chains],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CriterionSupportLinks:
        return cls(
            criterion_id=data["criterion_id"],
            chains=tuple(ChainLink.from_dict(c) for c in data.get("chains", ())),
            link_confidence=float(data["link_confidence"]),
            raw_link_confidence=float(data["raw_link_confidence"]),
            unlinked_reason=data.get("unlinked_reason"),
            reasons=tuple(Reason.from_dict(r) for r in data.get("reasons", ())),
            score_kind=data.get("score_kind", SCORE_KIND_UNCALIBRATED),
            suspicious=bool(data.get("suspicious", False)),
            algo_version=data.get("algo_version", CHAIN_ALGO_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SupportLinkSet:
    """Chains and confidences of one analysis, criteria in id order."""

    criteria: tuple[CriterionSupportLinks, ...] = ()
    algo_version: str = CHAIN_ALGO_VERSION
    score_kind: str = SCORE_KIND_UNCALIBRATED
    config: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()

    def for_criterion(self, criterion_id: str) -> CriterionSupportLinks | None:
        for item in self.criteria:
            if item.criterion_id == criterion_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "score_kind": self.score_kind,
            "config": self.config,
            "calibration": self.calibration,
            "diagnostics": list(self.diagnostics),
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SupportLinkSet:
        return cls(
            criteria=tuple(
                CriterionSupportLinks.from_dict(c) for c in data.get("criteria", ())
            ),
            algo_version=data.get("algo_version", CHAIN_ALGO_VERSION),
            score_kind=data.get("score_kind", SCORE_KIND_UNCALIBRATED),
            config=dict(data.get("config", {})),
            calibration=data.get("calibration"),
            diagnostics=tuple(data.get("diagnostics", ())),
        )

    @classmethod
    def from_json(cls, text: str) -> SupportLinkSet:
        return cls.from_dict(json.loads(text))
