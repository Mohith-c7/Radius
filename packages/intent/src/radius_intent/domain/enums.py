"""Intent domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class IntentSourceKind(StrEnum):
    """Where a piece of intent text came from."""

    PR_BODY = "pr_body"
    PR_TITLE = "pr_title"
    ISSUE = "issue"
    COMMIT_MESSAGE = "commit_message"
    SPEC_FILE = "spec_file"
    AGENT_PROMPT = "agent_prompt"
    COMMENT = "comment"


class ExtractionMethod(StrEnum):
    """How a criterion was produced (DEC-009: LLMs only propose)."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HUMAN = "human"


class Testability(StrEnum):
    """Testability rating of a criterion (DESIGN 6.1 step 4, IN-05).

    ``TESTABLE``, ``VAGUE`` and ``NON_FUNCTIONAL`` are the IN-01 names; they
    are aliases of the IN-05 categories, and the legacy stored strings
    (``"testable"``, ``"vague"``, ``"non_functional"``) still parse.
    """

    __test__ = False  # not a pytest class

    UNRATED = "unrated"
    #: Observable behavior with inputs/outputs or conditions.
    BEHAVIORAL_TESTABLE = "behavioral_testable"
    #: Refactor, rename, move, config, dependency or docs: checkable by diff.
    STRUCTURAL_CHECKABLE = "structural_checkable"
    #: Performance, security or accessibility with a threshold or named tool.
    NON_FUNCTIONAL_MEASURABLE = "non_functional_measurable"
    #: "Clean", "intuitive", "better" ... without a measure.
    SUBJECTIVE_OR_VAGUE = "subjective_or_vague"
    #: Needs human, product or legal judgment, or live external systems.
    UNTESTABLE_EXTERNAL = "untestable_external"

    # IN-01 names, kept as aliases.
    TESTABLE = "behavioral_testable"
    VAGUE = "subjective_or_vague"
    NON_FUNCTIONAL = "non_functional_measurable"

    @classmethod
    def _missing_(cls, value: object) -> Testability | None:
        """Parse the pre-IN-05 stored strings."""
        if isinstance(value, str):
            legacy = _LEGACY_VALUES.get(value)
            if legacy is not None:
                return cls(legacy)
        return None


_LEGACY_VALUES = {
    "testable": "behavioral_testable",
    "vague": "subjective_or_vague",
    "non_functional": "non_functional_measurable",
}


class CriterionState(StrEnum):
    """Human-confirmation lifecycle state of a criterion."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EDITED = "edited"
    #: Set by IN-06 when the source wording of a human-confirmed criterion changed.
    NEEDS_RECONFIRMATION = "needs_reconfirmation"
    #: Set by IN-06 when a human-confirmed criterion vanished from its sources.
    ORPHANED = "orphaned"
