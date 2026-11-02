"""Shared helpers for the extraction tests (not collected by pytest)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radius_intent.domain import IntentSource, IntentSourceKind

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "extraction"


def src(
    text: str,
    kind: IntentSourceKind = IntentSourceKind.PR_BODY,
    source_id: str = "pr-1",
    **flags: bool,
) -> IntentSource:
    """Build a source with a fixed fetch time."""
    return IntentSource.from_text(source_id, kind, text, NOW, **flags)
