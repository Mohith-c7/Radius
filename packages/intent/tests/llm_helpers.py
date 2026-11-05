"""Shared helpers for IN-04 tests (no network, no keys)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from radius_intent.domain import IntentSource, IntentSourceKind
from radius_intent.infrastructure.llm import (
    EnvEgressPolicy,
    FakeProvider,
    LlmCriterionExtractor,
    LlmExtractionConfig,
    LlmRequest,
)
from radius_shared.llm_guard import parse_data_blocks

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BODY = (
    "Users must be able to export reports as CSV files.\n"
    "The export should finish within five seconds for large reports."
)
ALLOW = EnvEgressPolicy(True, frozenset({"*"}))


def source(
    text: str = BODY,
    source_id: str = "pr_body",
    kind: IntentSourceKind = IntentSourceKind.PR_BODY,
) -> IntentSource:
    return IntentSource.from_text(source_id, kind, text, NOW)


def item(src: IntentSource, quote: str, text: str | None = None) -> dict[str, object]:
    start = src.text.index(quote)
    return {
        "source_id": src.source_id,
        "quote": quote,
        "start": start,
        "end": start + len(quote),
        "text": text or quote,
    }


def reply(*items: dict[str, object], **top: object) -> str:
    return json.dumps({"criteria": list(items), **top})


def blocks(request: LlmRequest) -> dict[str, str]:
    nonce = re.search(r"RADIUS_DATA_([A-Za-z0-9]+)", request.system).group(1)  # type: ignore[union-attr]
    parsed = parse_data_blocks(request.user, nonce)
    assert parsed is not None
    return parsed


def make(
    handler=None,
    *,
    config: LlmExtractionConfig | None = None,
    org: str = "org-1",
    **kwargs,
) -> tuple[LlmCriterionExtractor, FakeProvider]:
    provider = FakeProvider(handler)
    kwargs.setdefault("policy", ALLOW)
    kwargs.setdefault("environ", {})
    kwargs.setdefault("sleeper", lambda _s: None)
    ex = LlmCriterionExtractor(
        provider,
        organization_id=org,
        config=config or LlmExtractionConfig(enabled=True),
        **kwargs,
    )
    return ex, provider
