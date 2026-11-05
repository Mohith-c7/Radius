"""Enumerations of the evidence contract (design 3.1)."""

from enum import StrEnum


class EvidenceKind(StrEnum):
    """Alpha produces only the first two; the rest are reserved."""

    TEST_OUTCOME = "test_outcome"
    TAMPER_FINDING = "tamper_finding"
    # Reserved, not produced yet: MUTATION_RESULT, COVERAGE_RECORD,
    # STATIC_ANALYSIS, ATTESTATION, PROCESS_SIGNAL.


class EvidenceSource(StrEnum):
    CI_UPLOAD = "ci_upload"
    WORKER_RUN = "worker_run"  # reserved (D7)
    STATIC_RULES = "static_rules"


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    FLAKY = "flaky"  # failed then passed on rerun (F-11): neither pass nor fail
    NOT_RUN = "not_run"  # linked test with no reported case


class AuthoredBy(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    UNKNOWN = "unknown"


class IndependenceBasis(StrEnum):
    PRE_EXISTING_UNCHANGED = "pre_existing_unchanged"
    CHANGED_IN_PR = "changed_in_pr"


class AssertKind(StrEnum):
    VALUE_EQUALITY = "value_equality"
    APPROX_EQUALITY = "approx_equality"
    EXCEPTION_TYPE_MESSAGE = "exception_type_message"
    EXCEPTION_TYPE = "exception_type"
    MEMBERSHIP = "membership"
    COMPARISON_BOUND = "comparison_bound"
    LENGTH_CHECK = "length_check"
    TRUTHINESS = "truthiness"
    NONE_CHECK = "none_check"
    TYPE_CHECK = "type_check"
    MOCK_CALLED = "mock_called"
    SNAPSHOT = "snapshot"
    TAUTOLOGY = "tautology"
    NO_ASSERTION = "no_assertion"
    OTHER = "other"


class SupportState(StrEnum):
    """Per-criterion support state (DEC-008).

    Deliberately not ``radius_intent``'s ``CriterionState`` (confirmation
    lifecycle); see design finding F7.
    """

    PROVEN = "proven"
    WEAK = "weak"
    UNEVIDENCED = "unevidenced"
    CONTRADICTED = "contradicted"
    EXCLUDED = "excluded"


class Flag(StrEnum):
    """Orthogonal to state; any number per criterion."""

    TAMPERED = "tampered"
    FLAKY_EVIDENCE = "flaky_evidence"
    STALE_EVIDENCE = "stale_evidence"
    LOW_LINK_CONFIDENCE = "low_link_confidence"
    UNCONFIRMED = "unconfirmed"
    PENDING_RESULTS = "pending_results"
    STATIC_ONLY = "static_only"
    NO_STRONG_ASSERTION = "no_strong_assertion"
    NEEDS_TYPED_EVIDENCE = "needs_typed_evidence"
    NO_LINKED_TEST = "no_linked_test"
    #: Contract 3: a counted test is linked only by a hint the PR author supplied
    #: (head spec or PR body) that nobody independent confirmed; its link is capped.
    AUTHOR_SUPPLIED_HINT = "author_supplied_hint"
    #: Contract 5: at least one counted test of the criterion has a measured (mutation)
    #: detection power instead of the static assertion cap. ``static_only`` stays when
    #: some counted test is still unmeasured.
    MUTATION_MEASURED = "mutation_measured"


class Provenance(StrEnum):
    """Who supplied a criterion or a ``tests:``/``paths:`` hint (contract 3)."""

    AUTHOR_PR_BODY = "author_pr_body"
    AUTHOR_HEAD_SPEC = "author_head_spec"
    BASE_SPEC = "base_spec"
    HUMAN_CONFIRMED = "human_confirmed"
    LLM_PROPOSED = "llm_proposed"


#: Provenance values whose hints are NOT capped (the PR author did not control them).
TRUSTED_HINT_PROVENANCE: frozenset[str] = frozenset(
    {Provenance.BASE_SPEC.value, Provenance.HUMAN_CONFIRMED.value}
)
ALL_PROVENANCE: frozenset[str] = frozenset(p.value for p in Provenance)


class NodeKind(StrEnum):
    CRITERION = "criterion"
    SYMBOL = "symbol"
    TEST = "test"
    EVIDENCE = "evidence"
    FINDING = "finding"


class EdgeKind(StrEnum):
    IMPLEMENTED_BY = "implemented_by"  # criterion -> symbol (LK-02)
    EXERCISED_BY = "exercised_by"  # symbol -> test (LK-03)
    ADDRESSED_BY = "addressed_by"  # criterion -> test (VS-04 or intent.yml hint)
    PRODUCED = "produced"  # test -> evidence item
    AFFECTS = "affects"  # tamper finding -> test | symbol
