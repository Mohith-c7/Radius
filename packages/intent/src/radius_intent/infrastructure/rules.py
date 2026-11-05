"""Validation and hashing shared by every IntentRepository implementation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from radius_intent.domain import (
    Criterion,
    CriterionState,
    IntentSnapshot,
    IntentSource,
)
from radius_intent.interfaces.repository import (
    MAX_SOURCE_TEXT_BYTES,
    InvalidIdentifierError,
    SourceTooLargeError,
)

MAX_SOURCE_REF_CHARS = 255
MAX_EXTRACTOR_VERSION_CHARS = 64
MAX_CRITERION_ID_CHARS = 64
MAX_ACTOR_CHARS = 255


def parse_uuid(value: str, what: str) -> UUID:
    """Parse a canonical lowercase UUID string or raise."""
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        msg = f"{what} must be a UUID string."
        raise InvalidIdentifierError(msg) from exc
    if str(parsed) != value:
        msg = f"{what} must be a canonical lowercase UUID string."
        raise InvalidIdentifierError(msg)
    return parsed


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (naive input is assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def require_aware(value: datetime, what: str) -> datetime:
    """Reject naive datetimes at the persistence boundary."""
    if value.tzinfo is None:
        msg = f"{what} must be timezone-aware."
        raise InvalidIdentifierError(msg)
    return as_utc(value)


def check_text(value: str, what: str) -> None:
    """Reject NUL characters (PostgreSQL cannot store them)."""
    if "\x00" in value:
        msg = f"{what} contains a NUL character."
        raise SourceTooLargeError(msg)


def validate_source(source: IntentSource) -> None:
    """Enforce storage limits on one source."""
    if len(source.text.encode("utf-8")) > MAX_SOURCE_TEXT_BYTES:
        msg = f"Source text exceeds {MAX_SOURCE_TEXT_BYTES} bytes."
        raise SourceTooLargeError(msg)
    check_text(source.text, "Source text")
    if len(source.source_id) > MAX_SOURCE_REF_CHARS:
        msg = "Source id is too long."
        raise SourceTooLargeError(msg)
    check_text(source.source_id, "Source id")


def validate_criterion(criterion: Criterion) -> None:
    """Enforce storage limits on one criterion."""
    if len(criterion.id) > MAX_CRITERION_ID_CHARS:
        msg = "Criterion id is too long."
        raise InvalidIdentifierError(msg)
    if len(criterion.origin.extractor_version) > MAX_EXTRACTOR_VERSION_CHARS:
        msg = "extractor_version is too long."
        raise InvalidIdentifierError(msg)
    check_text(criterion.id, "Criterion id")
    check_text(criterion.text, "Criterion text")
    check_text(criterion.normalized_text, "Criterion normalized_text")
    check_text(criterion.origin.extractor_version, "extractor_version")
    if criterion.testability_rationale is not None:
        check_text(criterion.testability_rationale, "Rationale")


def snapshot_content_hash(snapshot: IntentSnapshot) -> str:
    """Hash snapshot content (not its id or created_at) for idempotent saves."""
    payload = {
        "analysis_id": snapshot.analysis_id,
        "version": snapshot.version,
        "parent": snapshot.parent_snapshot_id,
        "sources": [
            [r.kind.value, r.source_id, r.raw_text_hash] for r in snapshot.sources
        ],
        "criteria": [
            {
                "id": c.id,
                "text": c.text,
                "normalized_text": c.normalized_text,
                "origin": [
                    c.origin.source.kind.value,
                    c.origin.source.source_id,
                    c.origin.source.raw_text_hash,
                    as_utc(c.origin.retrieved_at).isoformat(),
                    c.origin.extraction_method.value,
                    c.origin.extractor_version,
                ],
                "span": [c.span.start, c.span.end],
                "weight": c.weight,
                "testability": c.testability.value,
                "rationale": c.testability_rationale,
                "state": c.state.value,
            }
            for c in snapshot.criteria
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def apply_state_change(
    criterion: Criterion, new_state: CriterionState, new_text: str | None
) -> Criterion:
    """Return ``criterion`` after a legal transition (domain rules apply)."""
    if new_state is CriterionState.EDITED:
        if new_text is None:
            msg = "new_text is required when moving to EDITED."
            raise InvalidIdentifierError(msg)
        check_text(new_text, "Edited text")
        return criterion.edit(new_text)
    if new_text is not None:
        msg = "new_text is only allowed when moving to EDITED."
        raise InvalidIdentifierError(msg)
    return criterion.transition_to(new_state)


def validate_actor(actor: str) -> None:
    """Require a non-blank actor that fits the column."""
    if not actor.strip() or len(actor) > MAX_ACTOR_CHARS:
        msg = "actor must be non-blank and at most 255 characters."
        raise InvalidIdentifierError(msg)
    check_text(actor, "actor")
