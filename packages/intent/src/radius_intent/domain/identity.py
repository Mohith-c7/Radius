"""Pure functions for text normalization, hashing and stable criterion ids."""

from __future__ import annotations

import hashlib
import unicodedata

#: Bump when normalization or id derivation changes (algo_version, plan 1.6).
CRITERION_ID_ALGO = "crit-id-v1"


def normalize_text(text: str) -> str:
    """Return the canonical form of ``text`` used for identity and dedupe.

    Steps: Unicode NFKC, drop format characters (category Cf: zero-width
    spaces/joiners, bidi marks), casefold, collapse all whitespace runs to a
    single space, strip. Deterministic and idempotent.
    """
    nfkc = unicodedata.normalize("NFKC", text)
    visible = "".join(ch for ch in nfkc if unicodedata.category(ch) != "Cf")
    return " ".join(visible.casefold().split())


def hash_text(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def criterion_id(normalized_text: str, source_ref: str) -> str:
    """Derive the stable criterion id.

    ``id = "crit_" + sha256(ALGO NUL source_ref NUL normalized_text)[:32]``.
    ``source_ref`` is ``SourceRef.key`` (``"<kind>:<source_id>"``). The input
    must already be normalized; call :func:`normalize_text` first.
    """
    payload = f"{CRITERION_ID_ALGO}\x00{source_ref}\x00{normalized_text}"
    return "crit_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
