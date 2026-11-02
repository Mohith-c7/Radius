"""Verdict v2 API schema (VS-09): the OpenAPI shape of ``verdict_v2.schema.json``.

Every text field derived from PR or issue content (criterion text, test ids,
snippets, reasons) is untrusted: JSON-escaped on the wire and rendered as text
only by clients. Unknown fields are tolerated so the alpha can grow additively.
``score`` is always ``null`` and ``score_kind`` always ``"none"``: v2 has no
calibrated number; the only score is the labelled ``v1`` block.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SupportStateName = Literal["proven", "weak", "unevidenced", "contradicted", "excluded"]
VerdictName = Literal["verified", "failed", "insufficient_evidence", "needs_review"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class ReasonOut(_Out):
    code: str
    detail: str
    rule_id: str | None = None
    ref: str | None = None


class SummaryOut(_Out):
    criteria_total: int
    proven: int
    weak: int
    unevidenced: int
    contradicted: int
    excluded: int
    uim: float = Field(ge=0, le=1, description="Unproven intent mass.")
    intent_coverage: float = Field(ge=0, le=1)
    tamper: dict[str, int] = Field(default_factory=dict)
    evidence_basis: Literal["static_only"] = "static_only"


class EvidenceItemOut(_Out):
    evidence_id: str
    test_id: str
    outcome: Literal["passed", "failed", "error", "skipped", "flaky", "not_run"]
    a_static: float
    d_eff: float
    i: float
    f: float
    flaky_f: float = 1.0
    tamper_penalty: float = 0.0
    q: float
    l: float  # noqa: E741
    term: float
    status: str
    contribution: float | None = None


class CriterionOut(_Out):
    criterion_id: str
    text: str = Field(description="UNTRUSTED. Render as text only.")
    state: SupportStateName
    S: float
    S_raw: float
    weight: float
    testability: str = ""
    lifecycle: str = ""
    flags: list[str] = Field(default_factory=list)
    reasons: list[ReasonOut] = Field(default_factory=list)
    best_link: dict[str, Any] | None = None
    items: list[EvidenceItemOut] = Field(default_factory=list)


class TamperFindingOut(_Out):
    finding_id: str
    rule_id: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    path: str
    reason: str = Field(description="UNTRUSTED. Render as text only.")
    check: str = ""
    confidence: float | None = None
    symbol: str | None = None
    test_id: str | None = None
    old_snippet: str | None = Field(default=None, description="UNTRUSTED.")
    new_snippet: str | None = Field(default=None, description="UNTRUSTED.")


class NextActionOut(_Out):
    code: str
    text: str
    criterion_id: str | None = None


class V1Out(_Out):
    verification_status: str
    confidence_score: float | None = None
    score_kind: str = Field(
        description="Honest label of the v1 number, e.g. heuristic_uncalibrated."
    )
    risk_level: str | None = None


class ErrorOut(_Out):
    code: str
    fallback: str | None = None


class VerdictV2Out(_Out):
    verdict_version: Literal[2] = 2
    algo_version: str
    profile: str
    mode: Literal["shadow", "on"]
    status: Literal["ok", "error", "skipped"]
    analysis_id: str
    head_sha: str
    revision: int
    computed_at: str | None = None
    verdict: VerdictName | None = Field(
        description="Null unless status is ok. Four states, no number."
    )
    pending: bool
    reasons: list[ReasonOut]
    score: None = Field(default=None, description="Always null: v2 has no number.")
    score_kind: Literal["none"] = "none"
    trust_probability: None = Field(
        default=None, description="Reserved; null until calibration exists."
    )
    summary: SummaryOut
    criteria: list[CriterionOut]
    tamper_findings: list[TamperFindingOut] = Field(default_factory=list)
    unlinked_symbols: list[str] = Field(default_factory=list)
    next_actions: list[NextActionOut] = Field(default_factory=list)
    justification: dict[str, Any]
    v1: V1Out | None = Field(
        default=None,
        description="Copy of the v1 result with its own score_kind; unchanged v1 "
        "is still served at /analyses/{id}/confidence.",
    )
    dashboard_url: str | None = None
    error: ErrorOut | None = Field(
        default=None, description="Present when status is error or skipped."
    )
