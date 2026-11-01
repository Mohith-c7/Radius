"""Scrub credentials from text before it is logged, stored, or published.

Error messages from git, HTTP clients, and subprocesses can echo the
command or URL that failed, which may embed an installation token
(``https://x-access-token:<token>@github.com/...``), an
``Authorization: Bearer <token>`` header, or an API key. Everything that
leaves the process (logs, ``analysis_jobs.last_error``, GitHub check
output) should pass through :func:`redact_secrets` first.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credentials embedded in URLs: scheme://user:password@host or scheme://token@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@'\"]+@"), rf"\1{REDACTED}@"),
    # Authorization headers (any scheme) up to the end of the value.
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(?:(bearer|token|basic)\s+)?[^\s'\",;]+"),
        rf"\1{REDACTED}",
    ),
    # Bare bearer tokens.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]+"), rf"\1 {REDACTED}"),
    # Radius / generic API-key headers and key=value secrets.
    (
        re.compile(
            r"(?i)\b(x-radius-api-key|x-api-key|api[_-]?key|access[_-]?token|"
            r"client[_-]?secret|private[_-]?key|password|secret|token)"
            r"(\s*[:=]\s*)[^\s'\",;&]+"
        ),
        rf"\1\2{REDACTED}",
    ),
    # GitHub token formats (installation, user, OAuth, refresh, fine-grained PAT).
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), REDACTED),
    # PEM private key blocks.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
)


def redact_secrets(text: object, *, max_length: int | None = None) -> str:
    """Return ``text`` with credentials replaced by ``[REDACTED]``.

    ``max_length`` truncates *after* redaction so a secret can never be
    half-cut into an unrecognisable (and therefore unredacted) fragment.
    """

    value = str(text)
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    if max_length is not None and len(value) > max_length:
        value = value[: max(0, max_length - 3)] + "..."
    return value
