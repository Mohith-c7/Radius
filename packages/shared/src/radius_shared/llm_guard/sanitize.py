"""Deterministic sanitiser for untrusted text bound for an LLM (QS-02).

Everything that originates in a repository or PR (titles, bodies, issue text,
commit messages, comments, file and test names, README, ``.radius/intent.yml``
values, tool output) is *untrusted*. :func:`sanitize_untrusted` is the only
supported way to turn such a string into an :class:`UntrustedText`, which is
the only type the prompt builder accepts.

Two kinds of findings are returned:

* ``strip`` findings: characters/segments that were removed or replaced
  (hidden unicode, HTML comments, ANSI escapes, NULs, control characters,
  secrets, over-length tails).
* ``flag`` findings: advisory heuristics (injection phrases, role spoofing,
  fake verdict strings...). Text is NOT altered for these. They exist for
  telemetry and review; they are never relied on for safety, because a
  denylist cannot be complete. Safety comes from delimiting (``prompt``) and
  output validation (``output``).
"""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from radius_shared.redaction import redact_secrets

DEFAULT_MAX_LENGTH = 20_000
TRUNCATION_MARKER = "\n[...TRUNCATED by Radius guard...]\n"
SECRET_MASK = "[REDACTED]"

_SEAL = object()

# Hidden / invisible characters. Stripped, not merely flagged.
_ZERO_WIDTH = {
    "​", "‌", "‍", "⁠", "﻿", "᠎", "­",
    "⁡", "⁢", "⁣", "⁤", "͏",
}  # fmt: skip
_BIDI = {
    "‎", "‏", "؜", "‪", "‫", "‬", "‭",
    "‮", "⁦", "⁧", "⁨", "⁩",
}  # fmt: skip


def _is_unicode_tag(ch: str) -> bool:
    return "\U000e0000" <= ch <= "\U000e007f" or "\U000e0100" <= ch <= "\U000e01ef"


_ANSI = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC ... BEL / ST
    r"|\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[@-Z\\-_]"  # two-byte escapes
    r"|\x1b"  # lone ESC
)
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
# C0/C1 control characters other than \t \n \r.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# --- advisory heuristics -------------------------------------------------

_I = re.IGNORECASE
_HEURISTICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "injection_phrase",
        re.compile(
            r"(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+)*"
            r"(?:previous|prior|above|earlier|preceding|system)\s+"
            r"(?:instructions?|prompts?|rules?|messages?|context)"
            r"|new\s+instructions?\s*:|from\s+now\s+on\s*,?\s*you\s+(?:are|will|must)"
            r"|you\s+are\s+now\s+(?:in\s+)?(?:a\s+|an\s+|the\s+)?\w+\s+mode"
            r"|ignora\s+(?:todas\s+)?las\s+instrucciones\s+anteriores"
            r"|ignorez?\s+(?:toutes\s+)?les\s+instructions\s+pr[eé]c[eé]dentes"
            r"|ignoriere?\s+(?:alle\s+)?(?:vorherigen|obigen)\s+anweisungen"
            r"|忽略(?:之前|以上|先前)的?(?:所有)?(?:指令|指示|说明)"
            r"|игнорируй(?:те)?\s+(?:все\s+)?(?:предыдущие|прежние)\s+инструкции",
            _I,
        ),
    ),
    (
        "role_spoof",
        re.compile(
            r"<\|(?:im_start|im_end|system|assistant|user)\|>|\[/?INST\]|<</?SYS>>"
            r"|^\s*(?:system|assistant|developer)\s*(?:message|prompt)?\s*:\s*"
            r"(?:you\s|ignore|disregard|always|never|from now|new\s|override|the\s+user)"
            r"|^\s*#{1,6}\s*(?:system|new)\s+(?:prompt|instructions?)\b",
            _I | re.MULTILINE,
        ),
    ),
    (
        "verdict_string",
        re.compile(
            r"\bRADIUS\s*[:=\-]\s*(?:PASS(?:ED)?|VERIFIED|SAFE|APPROVED|OK)\b"
            r"|\bmark\s+(?:this|the)\s+(?:pr|pull\s+request|change|commit)\s+(?:as\s+)?"
            r"(?:verified|safe|passed|approved|mergeable)"
            r"|\b(?:set|change)\s+(?:the\s+)?(?:verdict|status)\s+to\s+(?:verified|pass(?:ed)?|safe)"
            r"|\b(?:verdict|status)\s*[:=]\s*(?:verified|pass(?:ed)?|safe|approved)\b",
            _I,
        ),
    ),
    (
        "exfil_request",
        re.compile(
            r"\b(?:print|reveal|show|output|dump|echo|send|leak|repeat|disclose)\W+"
            r"(?:\w+\W+){0,4}?(?:env(?:ironment)?\s+(?:variables?|vars?)|secrets?|api[\s_-]?keys?"
            r"|credentials|passwords?|(?:system|initial)\s+prompt|your\s+instructions|\.env\b)",
            _I,
        ),
    ),
    (
        "tool_lure",
        re.compile(
            r"\b(?:you\s+(?:must|should|need\s+to|have\s+to)|please|now|first)\s*,?\s*"
            r"(?:fetch|curl|wget|visit|download|execute|call|invoke|run)\b"
            r"|\b(?:curl|wget)\s+\S+\s*\|\s*(?:ba)?sh\b|\$\([^)]*\)|`[^`\n]*\b(?:curl|wget|rm)\b[^`\n]*`",
            _I,
        ),
    ),
    (
        "delimiter_lookalike",
        re.compile(
            r"<<<\s*/?\s*(?:END[_-]?)?(?:RADIUS[_-]?)?DATA|</?(?:data|untrusted|source)\b[^>]*>",
            _I,
        ),
    ),
)

_B64_TOKEN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def decode_candidates(text: str) -> list[str]:
    """Return plausible decodings of encoded payloads found in ``text``.

    Base64 tokens (>= 24 chars) that decode to printable UTF-8 and a ROT13 view
    of the whole text. Used for advisory flagging and by test stubs that
    simulate a model decoding hidden instructions.
    """

    out: list[str] = []
    for token in _B64_TOKEN.findall(text):
        padded = token + "=" * (-len(token) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and decoded.isprintable():
            out.append(decoded)
    rot = codecs.decode(text, "rot_13")
    if rot != text:
        out.append(rot)
    return out


@dataclass(frozen=True)
class Finding:
    """One thing the sanitiser did or noticed."""

    code: str
    severity: str  # "strip" | "flag"
    count: int = 1
    detail: str = ""


@dataclass(frozen=True)
class UntrustedText:
    """Sanitised text from an untrusted origin.

    ``str()`` deliberately does NOT return the text so that an accidental
    f-string/concatenation cannot splice it into an instruction position.
    Use ``.text`` explicitly (the prompt builder does).
    """

    source_id: str
    kind: str
    text: str
    findings: tuple[Finding, ...] = ()
    original_length: int = 0
    original_sha256: str = ""
    _seal: object = field(default=None, repr=False, compare=False)

    def __str__(self) -> str:
        return f"<UntrustedText id={self.source_id} kind={self.kind} chars={len(self.text)}>"

    @property
    def is_sanitized(self) -> bool:
        return self._seal is _SEAL

    def finding_codes(self) -> frozenset[str]:
        return frozenset(f.code for f in self.findings)


_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


def is_valid_identifier(value: str) -> bool:
    return bool(_ID.match(value))


def sanitize_untrusted(
    raw: object,
    *,
    source_id: str,
    kind: str,
    max_length: int = DEFAULT_MAX_LENGTH,
    secrets: Iterable[str] = (),
) -> UntrustedText:
    """Sanitise ``raw`` deterministically and return it with its findings.

    ``source_id``/``kind`` are trusted, caller-chosen identifiers (never derived
    from untrusted text; file names etc. belong in the *text*).
    """

    if not is_valid_identifier(source_id) or not is_valid_identifier(kind):
        raise ValueError("source_id and kind must match [A-Za-z0-9_.:-]{1,64}")
    text = raw if isinstance(raw, str) else str(raw)
    original_length = len(text)
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    findings: list[Finding] = []

    def strip(code: str, count: int, detail: str = "") -> None:
        if count:
            findings.append(Finding(code, "strip", count, detail))

    n = text.count("\x00")
    text = text.replace("\x00", "")
    strip("null_byte", n)

    n = len(_ANSI.findall(text))
    text = _ANSI.sub("", text)
    strip("ansi_escape", n)

    counts = {"zero_width": 0, "bidi_control": 0, "unicode_tag": 0}
    kept: list[str] = []
    for ch in text:
        if ch in _ZERO_WIDTH:
            counts["zero_width"] += 1
        elif ch in _BIDI:
            counts["bidi_control"] += 1
        elif _is_unicode_tag(ch):
            counts["unicode_tag"] += 1
        else:
            kept.append(ch)
    text = "".join(kept)
    for code, count in counts.items():
        strip(code, count)

    n = len(_CONTROL.findall(text))
    text = _CONTROL.sub("", text)
    strip("control_char", n)

    comments = _HTML_COMMENT.findall(text)
    text = _HTML_COMMENT.sub("", text)
    strip(
        "html_comment",
        len(comments),
        "unterminated" if any(not c.endswith("-->") for c in comments) else "",
    )

    redacted = redact_secrets(text)
    for secret in sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True):
        redacted = redacted.replace(secret, SECRET_MASK)
    if redacted != text:
        strip("secret_redacted", max(1, redacted.count(SECRET_MASK)))
    text = redacted

    if len(text) > max_length:
        strip("truncated", 1, f"{len(text)}>{max_length}")
        text = text[:max_length] + TRUNCATION_MARKER

    for code, pattern in _HEURISTICS:
        hits = len(pattern.findall(text))
        if hits:
            findings.append(Finding(code, "flag", hits))
    if any(_has_flaggable(c) for c in decode_candidates(text)):
        findings.append(Finding("encoded_instruction", "flag", 1))

    return UntrustedText(
        source_id=source_id,
        kind=kind,
        text=text,
        findings=tuple(findings),
        original_length=original_length,
        original_sha256=digest,
        _seal=_SEAL,
    )


def _has_flaggable(decoded: str) -> bool:
    return any(p.search(decoded) for code, p in _HEURISTICS if code != "delimiter_lookalike")


def collect_env_secrets(environ: dict[str, str] | object, *, min_length: int = 8) -> list[str]:
    """Values of environment variables whose *names* look sensitive.

    Pass the result as ``secrets=`` to :func:`sanitize_untrusted` and as
    ``forbidden=`` to the output validator so env secrets can neither be sent
    to a model nor come back from one.
    """

    from radius_shared.redaction import is_sensitive_key

    items = environ.items() if hasattr(environ, "items") else []
    return sorted({v for k, v in items if is_sensitive_key(k) and isinstance(v, str) and len(v) >= min_length})
