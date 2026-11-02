"""Low-level text helpers: line splitting, comment masking, hidden chars.

Everything here is linear in the input size and regex-light on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EOL = re.compile(r"\r\n|\n|\r")
# Zero-width, bidi controls and BOM: common carriers of hidden instructions.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_INJECTION_HINTS = (
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard",
    "system prompt",
    "you are now",
    "as an ai",
    "mark this as",
    "approve this",
    "do not flag",
)
_CRITERIA_HINTS = ("- [", "* [", " must ", " shall ", " should ", "acceptance criteria")


@dataclass(frozen=True, slots=True)
class Line:
    """One physical line. ``text`` excludes the line terminator."""

    number: int  # 1-based
    start: int  # offset of the first character
    text: str

    @property
    def end(self) -> int:
        """Offset one past the last character of ``text``."""
        return self.start + len(self.text)


def split_lines(text: str) -> list[Line]:
    """Split on ``\\n``, ``\\r\\n`` and ``\\r`` keeping absolute offsets."""
    lines: list[Line] = []
    pos = 0
    number = 1
    for match in _EOL.finditer(text):
        lines.append(Line(number, pos, text[pos : match.start()]))
        pos = match.end()
        number += 1
    lines.append(Line(number, pos, text[pos:]))
    return lines


@dataclass(frozen=True)
class MaskedComment:
    """An HTML comment found (and blanked) in a source."""

    start: int
    end: int
    body: str
    terminated: bool


def mask_html_comments(text: str) -> tuple[str, list[MaskedComment]]:
    """Blank out ``<!-- ... -->`` keeping length and line breaks.

    Offsets in the returned text equal offsets in ``text``, so spans computed
    on the masked text are valid in the original. An unterminated comment
    swallows the rest of the input (as GitHub does).
    """
    if "<!--" not in text:
        return text, []
    pieces: list[str] = []
    found: list[MaskedComment] = []
    pos = 0
    while True:
        start = text.find("<!--", pos)
        if start < 0:
            pieces.append(text[pos:])
            break
        close = text.find("-->", start + 4)
        terminated = close >= 0
        end = close + 3 if terminated else len(text)
        pieces.append(text[pos:start])
        pieces.append(_blank(text[start:end]))
        body_end = close if terminated else end
        found.append(MaskedComment(start, end, text[start + 4 : body_end], terminated))
        pos = end
    return "".join(pieces), found


def _blank(chunk: str) -> str:
    return "".join(ch if ch in "\r\n" else " " for ch in chunk)


def comment_is_suspicious(comment: MaskedComment) -> bool:
    """Return whether a comment hides criteria-like or instruction-like text.

    Plain template hints (``<!-- Describe your changes -->``) are not flagged.
    """
    body = f" {' '.join(comment.body.split()).lower()} "
    if not body.strip():
        return False
    return any(h in body for h in _INJECTION_HINTS) or any(
        h in body for h in _CRITERIA_HINTS
    )


def has_invisible_characters(text: str) -> bool:
    """Return whether ``text`` contains zero-width or bidi control chars."""
    return _INVISIBLE.search(text) is not None


def collapse(text: str) -> str:
    """Collapse whitespace runs to single spaces and strip."""
    return " ".join(text.split())
