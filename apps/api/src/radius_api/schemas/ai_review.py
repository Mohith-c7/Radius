"""AI review API schema (DEC-041): advisory, AI-generated, never a verdict.

All text fields come from an LLM that read untrusted PR content. They were validated by
``radius_shared.ai_review`` (no links, markup, mentions or verdict claims) and must still be
rendered as plain text by clients. ``advisory`` and ``ai_generated`` are always ``true``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AiReviewItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    files: list[str] = Field(default_factory=list)


class AiReviewNotesOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    dropped: list[str] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)
    diff_truncated: bool = False


class AiReviewOut(BaseModel):
    """The stored review of one analysis, or why it is unavailable."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    status: Literal["ok", "unavailable"]
    reason_code: str | None = None
    advisory: Literal[True] = True
    ai_generated: Literal[True] = True
    label: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str
    generated_at: str
    summary: str | None = None
    risks: list[AiReviewItemOut] = Field(default_factory=list)
    tests: list[AiReviewItemOut] = Field(default_factory=list)
    missing_evidence: list[AiReviewItemOut] = Field(default_factory=list)
    next_steps: list[AiReviewItemOut] = Field(default_factory=list)
    notes: AiReviewNotesOut = Field(default_factory=AiReviewNotesOut)
