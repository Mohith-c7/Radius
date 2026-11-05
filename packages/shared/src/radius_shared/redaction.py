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

_SECRET_KEYS = (
    r"x-radius-api-key|x-api-key|api[_-]?key|access[_-]?token|"
    r"client[_-]?secret|private[_-]?key|password|secret|token"
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private keys first: later key=value rules would otherwise consume
    # only the "-----BEGIN" marker and leave the key body behind. A block
    # without an END marker (truncated output) is redacted to the end.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
        REDACTED,
    ),
    # JSON-style "key": "value" secrets.
    (
        re.compile(rf'(?i)("(?:{_SECRET_KEYS})"\s*:\s*)"[^"]*"'),
        rf'\1"{REDACTED}"',
    ),
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
            rf"(?i)\b({_SECRET_KEYS})"
            r"(\s*[:=]\s*)[^\s'\",;&]+"
        ),
        rf"\1\2{REDACTED}",
    ),
    # JSON Web Tokens (three base64url segments starting with a JSON header).
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),
    # AWS access key ids and common "sk-" style API keys.
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), REDACTED),
    # GitHub token formats (installation, user, OAuth, refresh, fine-grained PAT).
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), REDACTED),
)


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|signature|x-radius-api-key|x-api-key|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key|"
    r"password|passwd|secret|token|credential)"
)


def is_sensitive_key(key: object) -> bool:
    """Return whether a field/header name denotes a secret value."""

    return bool(_SENSITIVE_KEY.search(str(key)))


def redact_structure(value: object, *, key: object = None) -> object:
    """Redact secrets in nested dict/list/tuple data, keeping its shape.

    A value whose *key* looks sensitive (``Authorization``, ``token``,
    ``private_key`` ...) is replaced wholesale, whatever its content; other
    strings go through :func:`redact_secrets`.
    """

    if key is not None and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_structure(v, key=k) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_structure(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


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
