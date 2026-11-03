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
#: Contract 5: ``static_and_mutation`` only when RADIUS_FEATURE_MUTATION measured something.
EvidenceBasisName = Literal["static_only", "static_and_mutation"]
CriterionBasisName = Literal["static_only", "mutation_measured", "mutation_partial"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class SuggestedTestOut(_Out):
    """An LLM-proposed pytest snippet (DEC-034): gated, never executed, never evidence."""

    criterion_id: str
    test_code: str
    a_static: float = 0.0
    imports: dict[str, list[str]] = Field(default_factory=dict)
    model: str = ""
    provenance: Literal["llm_proposed"] = "llm_proposed"
    executed: Literal[False] = False
    evidence: Literal[False] = False


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
    evidence_basis: EvidenceBasisName = "static_only"
    author_hint_criteria: int = Field(
        default=0,
        ge=0,
        description="Criteria whose counted tests rely on an author-supplied, unconfirmed hint.",
    )
    tamper_waived: int = Field(
        default=0, description="Tamper findings accepted by a waiver (shown as WAIVED)."
    )


class HintOut(_Out):
    kind: Literal["paths", "tests"]
    value: str = Field(description="UNTRUSTED. Render as text only.")
    provenance: str = Field(
        description="author_pr_body | author_head_spec | base_spec | human_confirmed | llm_proposed"
    )


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
    basis: Literal["static", "mutation"] | None = Field(
        default=None, description="Contract 5, optional: how d_eff was obtained."
    )
    d_mut: float | None = Field(default=None, description="Contract 5, optional: kill rate.")
    d_mut_lcb: float | None = Field(
        default=None, description="Contract 5, optional: Wilson lower bound used as d_eff."
    )
    mutation_n: int | None = Field(
        default=None, description="Contract 5, optional: decided non-equivalent mutants."
    )
    mutation_killed: int | None = None


class SurvivorOut(_Out):
    mutant_id: str
    path: str = Field(description="UNTRUSTED. Render as text only.")
    line: int
    operator: str


class CriterionMutationOut(_Out):
    """Contract 5 (optional): what mutation measured for this criterion. Not a proof."""

    basis: CriterionBasisName
    n_mutants: int = 0
    killed: int = 0
    d_union: float | None = None
    d_union_lcb: float | None = None
    tests_measured: int = 0
    tests_total: int = 0
    survivors: list[SurvivorOut] = Field(
        default_factory=list, description="Mutants no linked test killed (gaps found by mutation)."
    )
    excluded: dict[str, int] = Field(default_factory=dict)
    d_reach: float | None = Field(default=None, description="Not computed in this slice.")
    d_reach_reason: str = ""
    reason: str = ""


class MutationRunOut(_Out):
    """Contract 5 (optional): the mutation run of this analysis."""

    status: Literal["measured", "unmeasured"]
    reason: str = ""
    engine: str = ""
    seed: int = 0
    generated: int = 0
    sampled: int = 0
    decided: int = 0
    killed: int = 0
    equivalent_suspects: int = 0
    skipped_for_budget: int = 0
    cache_hits: int = 0
    min_decided: int = 5
    ladder: list[str] = Field(default_factory=list)
    baseline_failed: int = 0
    baseline_flaky: int = 0


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
    provenance: str = Field(
        default="author_pr_body",
        description="Who supplied the criterion: author_pr_body | author_head_spec | base_spec "
        "| human_confirmed | llm_proposed.",
    )
    hints: list[HintOut] = Field(default_factory=list)
    reasons: list[ReasonOut] = Field(default_factory=list)
    best_link: dict[str, Any] | None = None
    items: list[EvidenceItemOut] = Field(default_factory=list)
    evidence_basis: CriterionBasisName | None = Field(
        default=None, description="Contract 5, optional: present when mutation was enabled."
    )
    mutation: CriterionMutationOut | None = None


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
    waived: bool = Field(
        default=False,
        description="True when a valid waiver accepts this finding. It is still listed.",
    )
    waiver: dict[str, Any] | None = Field(
        default=None,
        description="id, reason (UNTRUSTED), owner, expires of the waiver that applies.",
    )


class PolicyOut(_Out):
    """Resolved ``.radius/policy.yml`` (read from the base branch). Contract 3."""

    present: bool
    status: str = Field(description="ok | invalid | unreadable | too_large")
    mode: Literal["advisory", "blocking"] | None = Field(
        default=None,
        description="Only changes the Check Run conclusion mapping, never the verdict.",
    )
    source: dict[str, Any] = Field(default_factory=dict)
    head_policy: str = "ignore"
    thresholds: dict[str, float] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(
        default_factory=list, description="Which setting came from which policy line."
    )
    ignored_head: list[dict[str, Any]] = Field(default_factory=list)
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    tamper: dict[str, Any] = Field(default_factory=dict)
    unmet: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list, description="UNTRUSTED text.")
    warnings: list[str] = Field(default_factory=list, description="UNTRUSTED text.")


class WaiversOut(_Out):
    """Waiver audit record of this verdict. Contract 3."""

    status: str
    source: dict[str, Any] = Field(default_factory=dict)
    applied: list[dict[str, Any]] = Field(default_factory=list)
    ignored: list[dict[str, Any]] = Field(
        default_factory=list, description="Expired, invalid or non-waivable waivers, with the code."
    )
    audit_digest: str | None = None
    evaluated_on: str | None = None


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


class PresentationOut(_Out):
    verdict_label: str
    state_labels: dict[str, str]
    legend: str
    disclaimer: str
    summary_text: str


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
    contract_version: str | None = Field(
        default=None, description="Version of the verdict v2 data contract."
    )
    alpha: Literal[True] = Field(
        default=True, description="Always true while v2 is an alpha: wording must say so."
    )
    calibrated: Literal[False] = Field(
        default=False, description="Always false: thresholds are uncalibrated."
    )
    evidence_basis: EvidenceBasisName = Field(
        default="static_only",
        description="What the evidence is: static assertion strength (static_only), or static "
        "plus mutation-measured detection for some criteria (static_and_mutation, contract 5).",
    )
    presentation: PresentationOut | None = Field(
        default=None,
        description="User-facing wording (alpha): use it instead of the raw enum values.",
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
    policy: PolicyOut | None = Field(
        default=None, description="Present when the base branch has a .radius/policy.yml."
    )
    mutation: MutationRunOut | None = Field(
        default=None, description="Contract 5: present only when RADIUS_FEATURE_MUTATION ran."
    )
    waivers: WaiversOut | None = Field(
        default=None, description="Present when the base branch has a .radius/waivers.yml."
    )
    suggested_tests: list[SuggestedTestOut] = Field(
        default_factory=list,
        description="Opt-in (RADIUS_FEATURE_SUGGEST_TESTS): LLM-proposed pytest snippets for "
        "unevidenced or weak criteria, gated deterministically. Not run, not evidence; the "
        "verdict does not depend on them.",
    )
