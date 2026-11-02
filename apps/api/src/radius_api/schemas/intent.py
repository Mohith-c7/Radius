"""Intent API schemas (IN-08).

Requests use camelCase aliases and reject unknown fields; responses use
snake_case like the other Radius resources. Every free-text field is untrusted
data: it is JSON-escaped on the wire and must be escaped by clients before it
is rendered as HTML.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from radius_intent.domain import IntentSourceKind

SubmittableKind = Literal["agent_prompt", "spec_file", "pr_body", "pr_title", "issue"]


class _Request(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SubmitIntentSourceRequest(_Request):
    """Submit or replace one intent source of an analysis."""

    kind: SubmittableKind = Field(
        description="agent_prompt, spec_file (.radius/intent.yml), pr_body, "
        "pr_title or issue."
    )
    source_id: str | None = Field(
        default=None,
        alias="sourceId",
        description="Identity of the source within its kind (default per kind). "
        "Submitting the same kind and sourceId replaces the earlier text.",
    )
    text: str = Field(description="Source text, at most 64 KiB (UTF-8).")

    def source_kind(self) -> IntentSourceKind:
        """Return the domain enum for ``kind``."""
        return IntentSourceKind(self.kind)


class CriterionActionRequest(_Request):
    """Confirm, reject, reopen or edit one criterion."""

    action: Literal["confirm", "reject", "edit", "reopen"]
    text: str | None = Field(
        default=None, description="New wording; required for (only) edit."
    )
    reason: str | None = Field(default=None, description="Optional audit note.")

    @model_validator(mode="after")
    def _text_only_for_edit(self) -> Self:
        if self.action == "edit" and self.text is None:
            msg = "text is required when action is edit."
            raise ValueError(msg)
        if self.action != "edit" and self.text is not None:
            msg = "text is only allowed when action is edit."
            raise ValueError(msg)
        return self


class AddCriterionRequest(_Request):
    """Add a human-authored criterion (confirmed on creation)."""

    text: str = Field(description="The criterion statement, at most 2000 characters.")
    reason: str | None = Field(default=None, description="Optional audit note.")


class SpanView(BaseModel):
    """Half-open character range in a source text."""

    source_id: str
    start: int
    end: int


class OriginView(BaseModel):
    """Provenance of a criterion."""

    method: Literal["deterministic", "llm", "human"]
    extractor_version: str
    source_kind: str
    source_id: str
    source_hash: str
    retrieved_at: datetime


class HintsView(BaseModel):
    """Author-supplied linking hints."""

    paths: list[str] = []
    tests: list[str] = []
    label: str | None = None


class CriterionView(BaseModel):
    """One criterion with provenance."""

    id: str
    text: str
    origin: OriginView
    span: SpanView
    weight: float
    testability: str
    testability_rationale: str | None = None
    state: str
    hints: HintsView


class SourceSummaryView(BaseModel):
    """A source a snapshot cites, without its text."""

    kind: str
    source_id: str
    raw_text_hash: str
    length: int | None = Field(
        description="Characters of stored text; null if the text is unavailable."
    )
    truncated: bool
    suspicious_content_removed: bool
    fetched_at: datetime | None


class SourceDetailView(SourceSummaryView):
    """A source including its sanitized text (for span highlighting)."""

    text: str


class SnapshotSummaryView(BaseModel):
    """One snapshot in the history list."""

    id: str
    analysis_id: str
    version: int
    parent_snapshot_id: str | None
    created_at: datetime
    criteria_count: int
    state_counts: dict[str, int]
    source_count: int


class SnapshotView(SnapshotSummaryView):
    """A full snapshot."""

    etag: str
    criteria: list[CriterionView]
    sources: list[SourceSummaryView]


class DiagnosticView(BaseModel):
    """Something noteworthy about a build (never aborts it)."""

    code: str
    source: str | None
    detail: str


class CarryEventView(BaseModel):
    """What happened to a criterion that carried a human decision."""

    action: str
    criterion_id: str
    previous_id: str | None
    state: str


class BuildReportView(BaseModel):
    """Diagnostics of one build."""

    diagnostics: list[DiagnosticView]
    carry_events: list[CarryEventView]
    absent_sources: list[str]


class SanitizationView(BaseModel):
    """What the sanitizer did to submitted text (codes only)."""

    removed: list[str]
    flagged: list[str]


class BuildResultView(BaseModel):
    """Outcome of a write that rebuilt the snapshot."""

    snapshot: SnapshotView
    created: bool = Field(
        description="False when the sources produced no change (no new version)."
    )
    report: BuildReportView
    sanitization: SanitizationView


class CriterionResultView(BaseModel):
    """Outcome of a criterion write."""

    criterion: CriterionView
    snapshot_id: str
    snapshot_version: int
    etag: str
    created: bool = False


class CriterionChangeView(BaseModel):
    """One audit row."""

    snapshot_id: str
    snapshot_version: int
    criterion_id: str
    old_state: str
    new_state: str
    actor: str
    changed_at: datetime
    old_text: str | None
    new_text: str | None
    reason: str | None


class CriterionSummaryView(BaseModel):
    """Compact criterion in a diff."""

    criterion_id: str
    text: str
    state: str
    source: str


class CriterionDeltaView(BaseModel):
    """A criterion present in both snapshots that differs."""

    criterion_id: str
    changed_fields: list[str]
    text_before: str
    text_after: str
    state_before: str
    state_after: str


class SnapshotDiffView(BaseModel):
    """Difference between two snapshots."""

    from_snapshot_id: str
    to_snapshot_id: str
    from_version: int
    to_version: int
    added: list[CriterionSummaryView]
    removed: list[CriterionSummaryView]
    changed: list[CriterionDeltaView]
    state_changed: list[CriterionDeltaView]
    moved: list[str]
    sources_added: list[str]
    sources_removed: list[str]
    sources_changed: list[str]
