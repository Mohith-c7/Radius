"""``VerdictV2View``: tolerant read model of the stored verdict payload.

Contract file (VS-00, then VD-06). Parses the JSON served at
``GET /api/v1/analyses/{id}/verdict-v2`` (``verdict_v2.schema.json``). Unknown
fields are ignored, missing optional fields get neutral defaults, and every
text field is untrusted: renderers must escape it. Stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _strs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(v for v in value if isinstance(v, str))


def _maps(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(v for v in value if isinstance(v, Mapping))


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class ReasonView:
    code: str
    detail: str
    rule_id: str | None = None
    ref: str | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> ReasonView:
        return cls(
            _str(data.get("code")),
            _str(data.get("detail")),
            _opt_str(data.get("rule_id")),
            _opt_str(data.get("ref")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "rule_id": self.rule_id,
            "ref": self.ref,
        }


@dataclass(frozen=True, slots=True)
class SummaryView:
    criteria_total: int = 0
    proven: int = 0
    weak: int = 0
    unevidenced: int = 0
    contradicted: int = 0
    excluded: int = 0
    uim: float = 0.0
    intent_coverage: float = 0.0
    tamper: dict[str, int] = field(default_factory=dict)
    evidence_basis: str = "static_only"

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> SummaryView:
        tamper = {
            str(k): v
            for k, v in _dict(data.get("tamper")).items()
            if isinstance(v, int) and not isinstance(v, bool)
        }
        return cls(
            _int(data.get("criteria_total")),
            _int(data.get("proven")),
            _int(data.get("weak")),
            _int(data.get("unevidenced")),
            _int(data.get("contradicted")),
            _int(data.get("excluded")),
            _num(data.get("uim")),
            _num(data.get("intent_coverage")),
            tamper,
            _str(data.get("evidence_basis"), "static_only"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_total": self.criteria_total,
            "proven": self.proven,
            "weak": self.weak,
            "unevidenced": self.unevidenced,
            "contradicted": self.contradicted,
            "excluded": self.excluded,
            "uim": self.uim,
            "intent_coverage": self.intent_coverage,
            "tamper": dict(self.tamper),
            "evidence_basis": self.evidence_basis,
        }


@dataclass(frozen=True, slots=True)
class ItemView:
    evidence_id: str
    test_id: str
    outcome: str
    status: str
    a_static: float = 0.0
    d_eff: float = 0.0
    i: float = 0.0
    f: float = 0.0
    flaky_f: float = 1.0
    tamper_penalty: float = 0.0
    q: float = 0.0
    l: float = 0.0  # noqa: E741
    term: float = 0.0
    contribution: float | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> ItemView:
        contribution = data.get("contribution")
        return cls(
            _str(data.get("evidence_id")),
            _str(data.get("test_id")),
            _str(data.get("outcome")),
            _str(data.get("status")),
            _num(data.get("a_static")),
            _num(data.get("d_eff")),
            _num(data.get("i")),
            _num(data.get("f")),
            _num(data.get("flaky_f"), 1.0),
            _num(data.get("tamper_penalty")),
            _num(data.get("q")),
            _num(data.get("l")),
            _num(data.get("term")),
            None if contribution is None else _num(contribution),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "test_id": self.test_id,
            "outcome": self.outcome,
            "status": self.status,
            "a_static": self.a_static,
            "d_eff": self.d_eff,
            "i": self.i,
            "f": self.f,
            "flaky_f": self.flaky_f,
            "tamper_penalty": self.tamper_penalty,
            "q": self.q,
            "l": self.l,
            "term": self.term,
            "contribution": self.contribution,
        }


@dataclass(frozen=True, slots=True)
class CriterionView:
    criterion_id: str
    text: str  # UNTRUSTED
    state: str
    S: float
    S_raw: float
    weight: float
    flags: tuple[str, ...] = ()
    testability: str = ""
    lifecycle: str = ""
    reasons: tuple[ReasonView, ...] = ()
    best_link: dict[str, Any] | None = None
    items: tuple[ItemView, ...] = ()

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> CriterionView:
        best = data.get("best_link")
        return cls(
            _str(data.get("criterion_id")),
            _str(data.get("text")),
            _str(data.get("state")),
            _num(data.get("S")),
            _num(data.get("S_raw")),
            _num(data.get("weight"), 1.0),
            _strs(data.get("flags")),
            _str(data.get("testability")),
            _str(data.get("lifecycle")),
            tuple(ReasonView.from_payload(r) for r in _maps(data.get("reasons"))),
            dict(best) if isinstance(best, Mapping) else None,
            tuple(ItemView.from_payload(i) for i in _maps(data.get("items"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "text": self.text,
            "state": self.state,
            "S": self.S,
            "S_raw": self.S_raw,
            "weight": self.weight,
            "flags": list(self.flags),
            "testability": self.testability,
            "lifecycle": self.lifecycle,
            "reasons": [r.to_dict() for r in self.reasons],
            "best_link": None if self.best_link is None else dict(self.best_link),
            "items": [i.to_dict() for i in self.items],
        }


@dataclass(frozen=True, slots=True)
class TamperView:
    finding_id: str
    rule_id: str
    severity: str
    path: str
    reason: str  # UNTRUSTED
    check: str = ""
    symbol: str | None = None
    test_id: str | None = None
    old_snippet: str | None = None  # UNTRUSTED
    new_snippet: str | None = None  # UNTRUSTED

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> TamperView:
        return cls(
            _str(data.get("finding_id")),
            _str(data.get("rule_id")),
            _str(data.get("severity")),
            _str(data.get("path")),
            _str(data.get("reason")),
            _str(data.get("check")),
            _opt_str(data.get("symbol")),
            _opt_str(data.get("test_id")),
            _opt_str(data.get("old_snippet")),
            _opt_str(data.get("new_snippet")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "reason": self.reason,
            "check": self.check,
            "symbol": self.symbol,
            "test_id": self.test_id,
            "old_snippet": self.old_snippet,
            "new_snippet": self.new_snippet,
        }


@dataclass(frozen=True, slots=True)
class NextActionView:
    code: str
    text: str  # UNTRUSTED
    criterion_id: str | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> NextActionView:
        return cls(
            _str(data.get("code")),
            _str(data.get("text")),
            _opt_str(data.get("criterion_id")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "text": self.text,
            "criterion_id": self.criterion_id,
        }


@dataclass(frozen=True, slots=True)
class VerdictV2View:
    """Everything a renderer needs; ``verdict`` is None when status is not ok."""

    analysis_id: str
    head_sha: str
    revision: int
    mode: str
    status: str
    verdict: str | None
    pending: bool
    algo_version: str
    profile: str
    summary: SummaryView
    reasons: tuple[ReasonView, ...] = ()
    criteria: tuple[CriterionView, ...] = ()
    tamper_findings: tuple[TamperView, ...] = ()
    unlinked_symbols: tuple[str, ...] = ()
    next_actions: tuple[NextActionView, ...] = ()
    justification: dict[str, Any] = field(default_factory=dict)
    v1: dict[str, Any] | None = None
    dashboard_url: str | None = None
    error: dict[str, Any] | None = None
    computed_at: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> VerdictV2View:
        """Parse a payload dict; unknown fields are ignored."""

        v1 = payload.get("v1")
        error = payload.get("error")
        return cls(
            analysis_id=_str(payload.get("analysis_id")),
            head_sha=_str(payload.get("head_sha")),
            revision=_int(payload.get("revision"), 1),
            mode=_str(payload.get("mode")),
            status=_str(payload.get("status")),
            verdict=_opt_str(payload.get("verdict")),
            pending=payload.get("pending") is True,
            algo_version=_str(payload.get("algo_version")),
            profile=_str(payload.get("profile")),
            summary=SummaryView.from_payload(_dict(payload.get("summary"))),
            reasons=tuple(ReasonView.from_payload(r) for r in _maps(payload.get("reasons"))),
            criteria=tuple(
                CriterionView.from_payload(c) for c in _maps(payload.get("criteria"))
            ),
            tamper_findings=tuple(
                TamperView.from_payload(t) for t in _maps(payload.get("tamper_findings"))
            ),
            unlinked_symbols=_strs(payload.get("unlinked_symbols")),
            next_actions=tuple(
                NextActionView.from_payload(a) for a in _maps(payload.get("next_actions"))
            ),
            justification=_dict(payload.get("justification")),
            v1=dict(v1) if isinstance(v1, Mapping) else None,
            dashboard_url=_opt_str(payload.get("dashboard_url")),
            error=dict(error) if isinstance(error, Mapping) else None,
            computed_at=_opt_str(payload.get("computed_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "head_sha": self.head_sha,
            "revision": self.revision,
            "mode": self.mode,
            "status": self.status,
            "verdict": self.verdict,
            "pending": self.pending,
            "algo_version": self.algo_version,
            "profile": self.profile,
            "summary": self.summary.to_dict(),
            "reasons": [r.to_dict() for r in self.reasons],
            "criteria": [c.to_dict() for c in self.criteria],
            "tamper_findings": [t.to_dict() for t in self.tamper_findings],
            "unlinked_symbols": list(self.unlinked_symbols),
            "next_actions": [a.to_dict() for a in self.next_actions],
            "justification": dict(self.justification),
            "v1": None if self.v1 is None else dict(self.v1),
            "dashboard_url": self.dashboard_url,
            "error": None if self.error is None else dict(self.error),
            "computed_at": self.computed_at,
        }
