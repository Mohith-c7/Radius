"""Stage B input DTOs (design 3.7).

Producers (LK-01/02/03/04, VS-04, EV-02, intent, DB) are adapted to these in
``apps/worker/.../verdict_v2/adapters.py``; tests and fixture bundles build them
directly. Plain data only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.model import AssertionFeatures, Reason
from radius_evidence.domain.serialization import Serializable


@dataclass(frozen=True, slots=True)
class CriterionInput(Serializable):
    criterion_id: str
    text: str
    weight: float
    testability: str  # radius_intent Testability value
    lifecycle: str  # proposed|confirmed|edited|needs_reconfirmation
    hints_paths: tuple[str, ...] = ()
    hints_tests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolInput(Serializable):
    symbol_id: str
    path: str
    qualified_name: str
    kind: str
    language: str
    change_kind: str
    is_behavioral: bool
    is_test: bool
    is_pseudo: bool  # <module>, <file>


@dataclass(frozen=True, slots=True)
class CriterionSymbolEdgeInput(Serializable):
    criterion_id: str
    symbol_id: str
    score: float
    rank: int
    by_linker: dict[str, float] = field(default_factory=dict)
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolTestEdgeInput(Serializable):
    symbol_id: str
    test_id: str
    score: float
    kind: str
    depth: int | None = None


@dataclass(frozen=True, slots=True)
class CriterionTestEdgeInput(Serializable):
    criterion_id: str
    test_id: str
    weight: float
    method: str
    bm25_raw: float | None = None


@dataclass(frozen=True, slots=True)
class TamperFindingInput(Serializable):
    finding_id: str
    rule_id: str
    check: str
    severity: str
    confidence: float
    path: str
    symbol: str | None = None
    test_id: str | None = None
    reason: str = ""
    old_snippet: str | None = None
    new_snippet: str | None = None


@dataclass(frozen=True, slots=True)
class CaseOutcomeInput(Serializable):
    test_id: str | None
    raw_file: str | None
    raw_classname: str | None
    raw_name: str | None
    outcome: Outcome


@dataclass(frozen=True, slots=True)
class StageAInput(Serializable):
    """Persisted inside the bundle after Stage A."""

    analysis_id: str
    repository_id: str
    head_sha: str
    changeset_ref: str
    criteria: tuple[CriterionInput, ...]
    symbols: tuple[SymbolInput, ...]
    criterion_symbol: tuple[CriterionSymbolEdgeInput, ...]
    symbol_test: tuple[SymbolTestEdgeInput, ...]
    criterion_test: tuple[CriterionTestEdgeInput, ...]
    assertions: tuple[AssertionFeatures, ...]
    tamper: tuple[TamperFindingInput, ...]
    tamper_waived: int = 0
    tamper_unanalyzable: tuple[str, ...] = ()
    changed_test_ids: frozenset[str] = frozenset()  # tests added/modified in the PR
    agent_signal: bool = False  # PR carries an agent trailer (EV-03-lite)
    degraded: tuple[str, ...] = ()  # e.g. "truncated", "unsupported_language:ts"
    algo_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StageBInput(Serializable):
    stage_a: StageAInput
    cases: tuple[CaseOutcomeInput, ...] = ()
    uploads: int = 0
    flaky_test_ids: frozenset[str] = frozenset()
    flaky_scores: dict[str, float] = field(default_factory=dict)
    results_received: bool = False  # at least one CI upload for this analysis and head
    ci_failed_cases: int = 0
