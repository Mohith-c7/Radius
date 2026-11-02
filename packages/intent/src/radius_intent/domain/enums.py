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
    """Testability rating of a criterion (DESIGN 6.1 step 4)."""

    __test__ = False  # not a pytest class

    UNRATED = "unrated"
    TESTABLE = "testable"
    VAGUE = "vague"
    NON_FUNCTIONAL = "non_functional"


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
