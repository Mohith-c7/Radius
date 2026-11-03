"""Stage B input DTOs (design 3.7).

Producers (LK-01/02/03/04, VS-04, EV-02, intent, DB) are adapted to these in
``apps/worker/.../verdict_v2/adapters.py``; tests and fixture bundles build them
directly. Plain data only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    #: Contract 3: who supplied the criterion text / its hints (see ``enums.Provenance``).
    provenance: str = "author_pr_body"
    hints_provenance: str = "author_pr_body"
    #: B-07 (optional): label of the actor who confirmed or edited the criterion (shown in the
    #: verdict). ``None`` for criteria nobody confirmed; never trusted as an identity.
    confirmed_by: str | None = field(default=None, metadata={"omit_none": True})


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
    #: Contract 3: provenance of a hint edge (empty for relevance edges).
    provenance: str = ""


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
class MutantInput(Serializable):
    """One mutant of a changed symbol and what the linked tests did with it.

    Contract 5. Only the site (``path:line``) and the operator id are kept, never the
    mutated code. ``status`` is ``killed`` / ``survived`` / ``timeout`` / ``error`` /
    ``flaky`` / ``skipped_for_budget``. ``killed_by`` holds test ids as they appear in
    ``symbol_test`` edges.
    """

    mutant_id: str
    symbol_id: str
    path: str
    line: int
    operator: str
    status: str
    killed_by: tuple[str, ...] = ()
    equivalent_suspect: bool = False


@dataclass(frozen=True, slots=True)
class MutationInput(Serializable):
    """Stage A mutation measurement (contract 5; absent when the flag is off).

    ``status`` is ``measured`` (a kill matrix exists; whether a given test has enough
    decided mutants is decided in Stage B) or ``unmeasured`` (``reason`` says why: the
    static cap applies everywhere). ``symbol_tests`` maps each mutated symbol id to the
    baseline-stable linked tests that were run against its mutants.
    """

    status: str
    reason: str = ""
    mutants: tuple[MutantInput, ...] = ()
    symbol_tests: dict[str, tuple[str, ...]] = field(default_factory=dict)
    baseline_failed: tuple[str, ...] = ()
    baseline_flaky: tuple[str, ...] = ()
    generated: int = 0
    sampled: int = 0
    skipped_for_budget: int = 0
    cache_hits: int = 0
    seed: int = 0
    min_decided: int = 5
    #: Degradation steps taken, in order (``sampled``, ``tier_a_only``, ``budget_cut``, ...).
    ladder: tuple[str, ...] = ()
    engine: str = ""
    operators: tuple[str, ...] = ()
    image: str = ""


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
    #: Contract 2: the subset of ``changed_test_ids`` that is NEW in the PR (reason
    #: ``test_added_in_pr`` instead of ``test_modified_in_pr``). Empty = unknown.
    added_test_ids: frozenset[str] = frozenset()
    #: Contract 2: optional per-test agent signal (test id -> trailer seen); a test not
    #: in the map falls back to ``agent_signal``.
    agent_signal_by_test: dict[str, bool] = field(default_factory=dict)
    degraded: tuple[str, ...] = ()  # e.g. "truncated", "unsupported_language:ts"
    algo_versions: dict[str, str] = field(default_factory=dict)
    #: Contract 3: raw ``.radius/policy.yml`` / ``waivers.yml`` captured at the BASE ref
    #: (``radius_evidence.policy.repo_config``). Empty = no repository config read.
    repo_config: dict[str, Any] = field(default_factory=dict)
    #: Contract 5: mutation measurement (RADIUS_FEATURE_MUTATION). ``None`` = not run.
    mutation: MutationInput | None = field(default=None, metadata={"omit_none": True})


@dataclass(frozen=True, slots=True)
class StageBInput(Serializable):
    stage_a: StageAInput
    cases: tuple[CaseOutcomeInput, ...] = ()
    uploads: int = 0
    flaky_test_ids: frozenset[str] = frozenset()
    flaky_scores: dict[str, float] = field(default_factory=dict)
    results_received: bool = False  # at least one CI upload for this analysis and head
    ci_failed_cases: int = 0
