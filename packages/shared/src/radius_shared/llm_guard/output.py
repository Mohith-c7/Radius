"""Strict validation of LLM output ("LLM proposes, evidence disposes", DEC-009).

The only accepted shape is::

    {"criteria": [{"source_id": str, "quote": str, "start": int, "end": int, "text": str}]}

* ``quote`` must equal ``source.text[start:end]`` for a known source, so every
  proposal is anchored in evidence that already exists.
* Any key anywhere that names a verdict-like field is rejected outright
  (``verdict_field``); unknown keys are rejected (``schema``).
* ``text`` may not contain URLs/markup, shell-ish commands, fake verdict
  strings, hidden characters, secrets, the nonce or system-prompt fragments.
* Nothing in the output is ever fetched or executed by this module.

Any violation raises :class:`OutputRejected` (fail closed: callers fall back
to the deterministic path).
"""

from __future__ import annotations

import base64
import codecs
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from radius_shared.llm_guard.sanitize import UntrustedText


class OutputRejected(ValueError):
    """The model output violated the contract. ``code`` is a stable identifier."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class OutputLimits:
    max_raw_bytes: int = 65_536
    max_criteria: int = 50
    max_text_chars: int = 500
    max_quote_chars: int = 1_000
    max_depth: int = 6


@dataclass(frozen=True)
class Criterion:
    """A proposal. It carries no verdict-like field by construction."""

    source_id: str
    text: str
    quote: str
    start: int
    end: int


FORBIDDEN_KEYS = frozenset(
    {
        "verdict", "status", "state", "result", "results", "decision", "outcome",
        "verified", "verification", "passed", "pass", "fail", "failed", "approve",
        "approved", "safe", "mergeable", "merge", "confidence", "score", "risk",
        "conclusion", "recommendation", "check_run", "satisfied", "covered",
        "tool_calls", "tool_call", "function_call", "command", "commands", "url", "urls",
    }
)  # fmt: skip
_ALLOWED_TOP = {"criteria"}
_ALLOWED_ITEM = {"source_id", "quote", "start", "end", "text"}

_URL = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]{1,15}://|\bwww\.|\bdata:|\bjavascript:|\bmailto:|\]\(|</?[a-z!][^>]*>)"
)
_COMMAND = re.compile(
    r"\$\(|&&|\|\||;\s*(?:rm|curl|wget|sh|bash|nc)\b|\|\s*(?:ba)?sh\b"
    r"|(?:^|[\s;|&])(?:curl|wget|nc|ncat|bash|zsh|powershell|pwsh|sudo|chmod|chown|eval)\s+[-\w./$\"']"
    r"|\brm\s+-[a-z]*[rf]",
    re.IGNORECASE,
)
_VERDICT_TEXT = re.compile(
    r"(?i)\bRADIUS\s*[:=\-]\s*(?:PASS(?:ED)?|VERIFIED|SAFE|APPROVED|OK)\b"
    r"|\b(?:verdict|status|result)\s*[:=]\s*(?:verified|pass(?:ed)?|safe|approved|success)\b"
    r"|\bmark(?:ed)?\s+(?:this|the)\s+(?:pr|pull\s+request)\s+(?:as\s+)?(?:verified|safe|passed)"
)
_BAD_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}


def secret_variants(secret: str) -> set[str]:
    """Plain, base64, hex, ROT13 and reversed forms of ``secret``."""

    raw = secret.encode("utf-8")
    return {
        secret,
        secret[::-1],
        codecs.encode(secret, "rot_13"),
        base64.b64encode(raw).decode().rstrip("="),
        raw.hex(),
    }


def contains_secret(text: str, secrets: Iterable[str]) -> bool:
    lowered = text.lower()
    for secret in secrets:
        if not secret or len(secret) < 6:
            continue
        if any(v.lower() in lowered for v in secret_variants(secret)):
            return True
    return False


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise OutputRejected("bad_json", "duplicate key")
        out[key] = value
    return out


def _scan_keys(node: object, depth: int, limits: OutputLimits) -> None:
    if depth > limits.max_depth:
        raise OutputRejected("schema", "nesting too deep")
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).strip().lower() in FORBIDDEN_KEYS:
                raise OutputRejected("verdict_field", f"forbidden key {key!r}")
            _scan_keys(value, depth + 1, limits)
    elif isinstance(node, list):
        for item in node:
            _scan_keys(item, depth + 1, limits)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_text(
    text: str,
    *,
    forbidden: Sequence[str],
    system_prompt: str,
    limits: OutputLimits,
) -> None:
    if not text.strip() or len(text) > limits.max_text_chars:
        raise OutputRejected("limits", "criterion text empty or too long")
    if contains_secret(text, forbidden):
        raise OutputRejected("leak", "secret, nonce or prompt material in text")
    if system_prompt and len(system_prompt) >= 32:
        window = 32
        for i in range(0, len(system_prompt) - window + 1, 8):
            if system_prompt[i : i + window] in text:
                raise OutputRejected("leak", "system prompt fragment in text")
    if any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in text):
        raise OutputRejected("charset", "non-printable character in text")
    if _URL.search(text):
        raise OutputRejected("url", "URL or markup in text")
    if _COMMAND.search(text):
        raise OutputRejected("command", "command-like content in text")
    if _VERDICT_TEXT.search(text):
        raise OutputRejected("verdict_string", "verdict-like string in text")


def validate_criteria_output(
    raw: object,
    *,
    sources: Sequence[UntrustedText],
    forbidden: Sequence[str] = (),
    system_prompt: str = "",
    limits: OutputLimits | None = None,
) -> tuple[Criterion, ...]:
    """Parse and validate ``raw``; return criteria or raise :class:`OutputRejected`.

    ``forbidden`` lists values that must never appear in output (env secrets,
    the nonce). ``system_prompt`` enables the prompt-leak check.
    """

    limits = limits or OutputLimits()
    if not isinstance(raw, str):
        raise OutputRejected("bad_json", "output is not a string")
    if len(raw.encode("utf-8", "replace")) > limits.max_raw_bytes:
        raise OutputRejected("too_large", "output exceeds byte cap")
    if contains_secret(raw, forbidden):
        raise OutputRejected("leak", "secret or nonce in raw output")
    try:
        doc = json.loads(
            raw.strip(),
            object_pairs_hook=_no_duplicates,  # type: ignore[arg-type]
            parse_constant=lambda c: (_ for _ in ()).throw(OutputRejected("bad_json", c)),
        )
    except OutputRejected:
        raise
    except (ValueError, RecursionError) as exc:
        raise OutputRejected("bad_json", type(exc).__name__) from None

    _scan_keys(doc, 0, limits)
    if not isinstance(doc, dict) or set(doc) != _ALLOWED_TOP:
        raise OutputRejected("schema", "top level must be exactly {criteria}")
    items = doc["criteria"]
    if not isinstance(items, list):
        raise OutputRejected("schema", "criteria must be a list")
    if len(items) > limits.max_criteria:
        raise OutputRejected("limits", "too many criteria")

    by_id = {s.source_id: s for s in sources}
    out: list[Criterion] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != _ALLOWED_ITEM:
            raise OutputRejected("schema", "criterion keys must be exactly the schema keys")
        sid, quote, start, end, text = (item[k] for k in ("source_id", "quote", "start", "end", "text"))
        if not (isinstance(sid, str) and isinstance(quote, str) and isinstance(text, str)):
            raise OutputRejected("schema", "wrong field types")
        if not (_is_int(start) and _is_int(end)):
            raise OutputRejected("schema", "span must be integers")
        source = by_id.get(sid)
        if source is None:
            raise OutputRejected("unknown_source", "source_id not supplied")
        if not (0 <= start < end <= len(source.text)):
            raise OutputRejected("span_mismatch", "span outside source")
        if len(quote) > limits.max_quote_chars or source.text[start:end] != quote:
            raise OutputRejected("span_mismatch", "quote does not match source span")
        _check_text(text, forbidden=forbidden, system_prompt=system_prompt, limits=limits)
        out.append(Criterion(sid, text, quote, start, end))
    return tuple(out)
