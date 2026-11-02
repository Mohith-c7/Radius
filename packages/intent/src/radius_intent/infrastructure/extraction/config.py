"""Configuration and constants for deterministic extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from radius_intent.domain import IntentSourceKind

#: Bump when any rule, threshold default or tie-break changes (plan 1.6).
DETERMINISTIC_EXTRACTOR_VERSION = "det-extract-v1"

#: Headings (cleaned, lowercase, full match) whose lists are criteria.
DEFAULT_SECTION_PATTERN = (
    r"acceptance criteria|acceptance|success criteria|requirements?"
    r"|expected(?: (?:behaviou?r|results?|outcomes?))?"
    r"|definition of done|dod|done when|scope|steps to (?:verify|test)"
)

#: Headings whose content is process noise, never criteria.
DEFAULT_EXCLUDED_PATTERN = (
    r"(?:pr |pull request |pre[- ]?merge |reviewer )?checklist"
    r"|types? of changes?|screenshots?(?: .*)?|related (?:issues?|prs?)"
    r"|notes?(?: for reviewers?)?|additional (?:context|notes|information)"
    r"|release notes|changelog|breaking changes?|how (?:has this been|to) tested"
    r"|test plan|testing"
)

#: Table column headers (cleaned, lowercase, full match) holding criteria.
DEFAULT_TABLE_COLUMN_PATTERN = (
    r"criteri(?:on|a)|acceptance(?: criteri(?:on|a))?|requirements?"
    r"|expected(?: (?:behaviou?r|results?|outcomes?))?"
)

#: Higher wins when near-duplicates from several sources are merged.
SOURCE_PRIORITY: dict[IntentSourceKind, int] = {
    IntentSourceKind.SPEC_FILE: 100,
    IntentSourceKind.AGENT_PROMPT: 90,
    IntentSourceKind.ISSUE: 70,
    IntentSourceKind.PR_BODY: 60,
    IntentSourceKind.PR_TITLE: 40,
    IntentSourceKind.COMMIT_MESSAGE: 30,
    IntentSourceKind.COMMENT: 20,
}


@dataclass(frozen=True)
class ExtractionConfig:
    """Tunable extraction parameters. Same config + input => same output.

    The three ``*_pattern`` strings are regular expressions applied with
    ``re.fullmatch`` to cleaned lowercase text. They are trusted
    configuration (never taken from a source), so they must not be
    catastrophic.
    """

    section_pattern: str = DEFAULT_SECTION_PATTERN
    excluded_pattern: str = DEFAULT_EXCLUDED_PATTERN
    table_column_pattern: str = DEFAULT_TABLE_COLUMN_PATTERN
    similarity_threshold: float = 0.8
    max_criteria_per_source: int = 500
    max_item_chars: int = 2000
    max_sentence_chars: int = 400
    max_list_depth: int = 64

    def __post_init__(self) -> None:
        if not 0 < self.similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be in (0, 1].")
        limits = (
            self.max_criteria_per_source,
            self.max_item_chars,
            self.max_sentence_chars,
            self.max_list_depth,
        )
        if min(limits) < 1:
            raise ValueError("Limits must be >= 1.")
        for pattern in (
            self.section_pattern,
            self.excluded_pattern,
            self.table_column_pattern,
        ):
            re.compile(pattern)

    def compiled(self) -> CompiledConfig:
        """Return the compiled regexes for this config."""
        return CompiledConfig(
            section=re.compile(self.section_pattern),
            excluded=re.compile(self.excluded_pattern),
            table_column=re.compile(self.table_column_pattern),
        )


@dataclass(frozen=True)
class CompiledConfig:
    """Compiled patterns derived from an :class:`ExtractionConfig`."""

    section: re.Pattern[str]
    excluded: re.Pattern[str]
    table_column: re.Pattern[str]


def source_priority(kind: IntentSourceKind) -> int:
    """Return the dedupe priority of ``kind``."""
    return SOURCE_PRIORITY[kind]
