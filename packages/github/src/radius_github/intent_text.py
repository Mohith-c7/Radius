"""Hygiene for fetched intent text (IN-02).

Every string fetched from GitHub (PR title/body, issue text, commit messages,
the spec file) is untrusted. :func:`prepare_text` turns it into the text that is
stored and later handed to extractors:

1. lone surrogates are replaced (JSON from GitHub can carry them);
2. ``raw_text_hash`` is the SHA-256 of that text *as fetched*, before anything
   below, so an upstream edit is detectable even when it only changes hidden
   content;
3. encoding is normalized: leading BOM removed, newlines to ``\\n``, Unicode NFC;
4. visibly-hidden HTML (``hidden`` attribute, ``display:none`` and friends) and
   Markdown comment links (``[//]: # (...)``) are removed;
5. :func:`radius_shared.llm_guard.sanitize_untrusted` removes NULs, ANSI escapes,
   zero-width/bidi/tag characters, control characters and HTML comments and
   masks secrets;
6. the result is cut to 64 KiB of UTF-8 with an explicit marker.

Nothing here executes or interprets the text; injection phrases are only
*flagged* (the sanitizer never rewrites them), exactly as for API submissions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from radius_intent.domain.identity import hash_text
from radius_shared.llm_guard import sanitize_untrusted

#: Per-source cap on stored UTF-8 bytes (IN-02; equals the repository limit).
MAX_SOURCE_BYTES = 64 * 1024
#: Raw input is cut here before any processing so hostile sizes cost bounded work.
MAX_PROCESSED_CHARS = 512 * 1024
TRUNCATION_MARKER = "\n[...truncated by Radius: source exceeds 64 KiB...]\n"

#: Sanitizer findings that mean hidden or non-visible content was removed.
HIDDEN_CONTENT_CODES = frozenset(
    {
        "null_byte",
        "ansi_escape",
        "zero_width",
        "bidi_control",
        "unicode_tag",
        "control_char",
        "html_comment",
        "hidden_html",
    }
)

_BOM = "﻿"
_TAG = re.compile(r"<(?P<tag>[A-Za-z][A-Za-z0-9]{0,15})\b(?P<attrs>[^<>]{0,500})>")
_HIDDEN_ATTRS = re.compile(
    r"(?:^|\s)hidden(?:\s|=|/|$)"
    r"|style\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden"
    r"|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d])|height\s*:\s*0(?![.\d])"
    r"|width\s*:\s*0(?![.\d]))",
    re.IGNORECASE,
)
_MAX_HIDDEN_ELEMENTS = 200
_REFERENCE_COMMENT = re.compile(
    r"^[ \t]*\[(?://|comment|#)\]:[ \t]*(?:#|<>)[ \t]*"
    r"(?:\([^\n]*\)|\"[^\n]*\"|'[^\n]*')?[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)

_TRAILER = re.compile(
    r"^(?:co-authored-by|co-developed-by|signed-off-by|reviewed-by|acked-by"
    r"|tested-by|reported-by|suggested-by|helped-by|cc|change-id|reviewed-on"
    r"|generated-by)[ \t]*:.*$",
    re.IGNORECASE,
)
_GENERATED_LINE = re.compile(
    r"^[ \t]*(?:\U0001f916[ \t]*)?generated with\b.*$", re.IGNORECASE
)


@dataclass(frozen=True)
class PreparedText:
    """Stored text plus the flags ingestion records about it."""

    text: str
    raw_text_hash: str
    truncated: bool
    suspicious_content_removed: bool
    #: Codes of everything removed (``strip``) or merely noticed (``flag``).
    findings: tuple[str, ...]

    @property
    def empty(self) -> bool:
        """True when nothing but whitespace is left."""
        return not self.text.strip()


def scrub_surrogates(text: str) -> str:
    """Replace lone surrogates so the string encodes as UTF-8."""
    return text.encode("utf-8", "replace").decode("utf-8")


def normalize_encoding(text: str) -> str:
    """Strip a leading BOM, normalize newlines to ``\\n`` and apply NFC."""
    text = text.lstrip(_BOM)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def strip_hidden_html(text: str) -> tuple[str, int]:
    """Remove elements that are invisible when rendered; return (text, count).

    Only elements with a ``hidden`` attribute or an inline style that hides them
    are removed (with their content up to the matching close tag, or just the
    opening tag when it is never closed). Markdown comment links are removed as
    well. Linear in the input apart from one ``str.find`` per hidden element,
    and bounded to :data:`_MAX_HIDDEN_ELEMENTS` elements.
    """
    removed = 0
    pieces: list[str] = []
    cursor = 0
    position = 0
    while removed < _MAX_HIDDEN_ELEMENTS:
        match = _TAG.search(text, position)
        if match is None:
            break
        position = match.end()
        if not _HIDDEN_ATTRS.search(match["attrs"]) or match.start() < cursor:
            continue
        tag = match["tag"].lower()
        closer = re.compile(rf"</{tag}\s*>", re.IGNORECASE).search(text, match.end())
        end = closer.end() if closer else match.end()
        pieces.append(text[cursor : match.start()])
        cursor = end
        position = max(position, end)
        removed += 1
    pieces.append(text[cursor:])
    text = "".join(pieces)
    text, links = _REFERENCE_COMMENT.subn("", text)
    return text, removed + links


def strip_commit_trailers(message: str) -> str:
    """Drop trailing git trailers and tool signatures, keeping the message text.

    Only the final block is touched: trailing blank lines, ``Co-Authored-By:``,
    ``Signed-off-by:``, ``Change-Id:`` and similar trailers, and "Generated with"
    signature lines. A line that merely looks like a trailer in the middle of the
    message is kept.
    """
    lines = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and (
        not lines[-1].strip()
        or _TRAILER.match(lines[-1].strip())
        or _GENERATED_LINE.match(lines[-1])
    ):
        lines.pop()
    return "\n".join(lines)


def truncate_utf8(text: str, max_bytes: int = MAX_SOURCE_BYTES) -> tuple[str, bool]:
    """Cut ``text`` to ``max_bytes`` of UTF-8 including the marker."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text, False
    budget = max_bytes - len(TRUNCATION_MARKER.encode("utf-8"))
    clipped = text.encode("utf-8")[:budget].decode("utf-8", "ignore")
    newline = clipped.rfind("\n")
    if newline > len(clipped) - 1024 and newline > 0:
        clipped = clipped[:newline]
    return clipped + TRUNCATION_MARKER, True


def prepare_text(
    raw: str,
    *,
    source_id: str,
    kind: str,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> PreparedText:
    """Normalize, sanitize and size-cap one fetched text (see module docs)."""
    raw = scrub_surrogates(raw)
    raw_hash = hash_text(raw)
    cut = len(raw) > MAX_PROCESSED_CHARS
    text = normalize_encoding(raw[:MAX_PROCESSED_CHARS])
    text, hidden = strip_hidden_html(text)
    cleaned = sanitize_untrusted(
        text,
        source_id=source_id,
        kind=kind,
        max_length=len(text) + 1,
    )
    body = cleaned.text.strip()
    body, over_limit = truncate_utf8(body, max_bytes)
    codes = [finding.code for finding in cleaned.findings]
    if hidden:
        codes.append("hidden_html")
    stripped = {f.code for f in cleaned.findings if f.severity == "strip"}
    if hidden:
        stripped.add("hidden_html")
    return PreparedText(
        text=body,
        raw_text_hash=raw_hash,
        truncated=over_limit or cut,
        suspicious_content_removed=bool(HIDDEN_CONTENT_CODES & stripped),
        findings=tuple(sorted(set(codes))),
    )


__all__ = [
    "HIDDEN_CONTENT_CODES",
    "MAX_PROCESSED_CHARS",
    "MAX_SOURCE_BYTES",
    "TRUNCATION_MARKER",
    "PreparedText",
    "normalize_encoding",
    "prepare_text",
    "scrub_surrogates",
    "strip_commit_trailers",
    "strip_hidden_html",
    "truncate_utf8",
]
