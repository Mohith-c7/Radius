"""IntentSource entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from radius_intent.domain.enums import IntentSourceKind
from radius_intent.domain.errors import InvalidSourceError
from radius_intent.domain.identity import hash_text
from radius_intent.domain.value_objects import SourceRef, is_sha256_hex


@dataclass(frozen=True)
class IntentSource:
    """One piece of raw intent text with its ingestion flags (IN-02 rules).

    ``text`` is the sanitized text that spans index into. ``raw_text_hash`` is
    the SHA-256 of the text as fetched (before truncation/sanitization), so an
    upstream edit is detectable. ``truncated`` and ``suspicious_content_removed``
    record that ingestion cut the text or stripped hidden/suspicious content.
    """

    source_id: str
    kind: IntentSourceKind
    text: str
    raw_text_hash: str
    fetched_at: datetime
    truncated: bool = False
    suspicious_content_removed: bool = False

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise InvalidSourceError("Source id must be non-empty.")
        if not is_sha256_hex(self.raw_text_hash):
            raise InvalidSourceError("raw_text_hash must be a SHA-256 hex digest.")
        if self.fetched_at.tzinfo is None:
            raise InvalidSourceError("fetched_at must be timezone-aware.")

    @classmethod
    def from_text(
        cls,
        source_id: str,
        kind: IntentSourceKind,
        text: str,
        fetched_at: datetime,
        *,
        raw_text: str | None = None,
        truncated: bool = False,
        suspicious_content_removed: bool = False,
    ) -> IntentSource:
        """Build a source, hashing ``raw_text`` (default: ``text``)."""
        return cls(
            source_id=source_id,
            kind=kind,
            text=text,
            raw_text_hash=hash_text(text if raw_text is None else raw_text),
            fetched_at=fetched_at,
            truncated=truncated,
            suspicious_content_removed=suspicious_content_removed,
        )

    @property
    def ref(self) -> SourceRef:
        """Return the lightweight reference to this source."""
        return SourceRef(self.kind, self.source_id, self.raw_text_hash)
