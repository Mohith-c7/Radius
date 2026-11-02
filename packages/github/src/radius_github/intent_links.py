"""Closing-keyword parser for linked issues (IN-02).

Finds the issues a pull request (or a commit message) declares it will close:
``fixes #12``, ``Closes: org/repo#7``, ``resolved https://github.com/o/r/issues/3``.

Rules (they follow GitHub's documented behavior, with the exceptions noted):

* Keywords: close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved,
  case-insensitive, optionally followed by ``:``. The keyword must start a word
  (``prefixes #1`` is not a link) and links exactly one reference; ``fixes #1,
  #2`` links only ``#1``, as on GitHub.
* References: ``#n``, ``owner/repo#n`` and ``https://github.com/owner/repo/issues/n``
  (pull-request URLs are not issues and are ignored).
* Ignored regions: fenced code blocks (backtick and tilde, any fence length,
  unterminated fences run to the end), inline code, HTML comments, blockquotes
  (``> ...``) and ``<code>``/``<pre>`` elements. Indented code blocks are NOT
  detected: an indented ``- fixes #1`` is far more often a nested list item.
* Deduplicated by ``(owner, repo, number)`` case-insensitively (``#5`` equals
  ``owner/repo#5`` in the PR's own repository), at most :data:`MAX_LINKED_ISSUES`.

Pure and offline. The input is untrusted; every regex is anchored on a literal
keyword and uses bounded, non-nested quantifiers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

#: Cap on issues fetched per analysis (the rest are reported as truncated).
MAX_LINKED_ISSUES = 10
_MAX_NUMBER = 999_999_999

_KEYWORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9_])?"
_REFERENCE = re.compile(
    rf"(?<![\w/.-])(?P<keyword>{_KEYWORDS})(?![\w])(?:[ \t]*:[ \t]*|[ \t]+)"
    rf"(?:"
    rf"https?://(?:www\.)?github\.com/(?P<uo>{_NAME})/(?P<ur>{_NAME})/issues/(?P<un>\d{{1,10}})(?![\w])"
    rf"|(?P<ro>{_NAME})/(?P<rr>{_NAME})#(?P<rn>\d{{1,10}})(?![\w])"
    rf"|#(?P<n>\d{{1,10}})(?![\w])"
    rf")",
    re.IGNORECASE,
)
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_HTML_CODE = re.compile(r"<(code|pre)\b[^>]{0,200}>.*?(?:</\1\s*>|\Z)", re.DOTALL | re.IGNORECASE)
_BACKTICK_RUN = re.compile(r"`+")
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")


@dataclass(frozen=True, order=True)
class IssueRef:
    """A reference to an issue, with owner and repo always filled in."""

    owner: str
    repo: str
    number: int

    @property
    def key(self) -> tuple[str, str, int]:
        """Case-insensitive identity."""
        return (self.owner.lower(), self.repo.lower(), self.number)

    def label(self) -> str:
        """Return ``owner/repo#n``."""
        return f"{self.owner}/{self.repo}#{self.number}"


def strip_ignored_regions(text: str) -> str:
    """Blank out code fences, inline code, HTML comments and blockquotes.

    Replaced regions become spaces/newlines so offsets and line structure of the
    remaining text are preserved.
    """
    text = _HTML_COMMENT.sub(_blank, text)
    text = _HTML_CODE.sub(_blank, text)
    out: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        stripped = line.rstrip("\r")
        match = _FENCE.match(stripped)
        if fence is None:
            if match and not (match["fence"][0] == "`" and "`" in match["info"]):
                fence = match["fence"]
                out.append(_blank_text(line))
            elif stripped.lstrip().startswith(">"):
                out.append(_blank_text(line))
            else:
                out.append(line)
            continue
        # Inside a fence: it closes on the same character, at least as long,
        # with nothing but whitespace after it.
        if (
            match
            and match["fence"][0] == fence[0]
            and len(match["fence"]) >= len(fence)
            and not match["info"].strip()
        ):
            fence = None
        out.append(_blank_text(line))
    return _blank_inline_code("\n".join(out))


def parse_closing_references(
    text: str,
    *,
    default_owner: str,
    default_repo: str,
) -> list[IssueRef]:
    """Return the issues ``text`` closes, in order of appearance (not capped)."""
    seen: set[tuple[str, str, int]] = set()
    found: list[IssueRef] = []
    for match in _REFERENCE.finditer(strip_ignored_regions(text or "")):
        if match["n"] is not None:
            owner, repo, raw = default_owner, default_repo, match["n"]
        elif match["rn"] is not None:
            owner, repo, raw = match["ro"], match["rr"], match["rn"]
        else:
            owner, repo, raw = match["uo"], match["ur"], match["un"]
        number = int(raw)
        if not 1 <= number <= _MAX_NUMBER:
            continue
        ref = IssueRef(owner, repo, number)
        if ref.key in seen:
            continue
        seen.add(ref.key)
        found.append(ref)
    return found


def collect_linked_issues(
    texts: Iterable[str],
    *,
    default_owner: str,
    default_repo: str,
    limit: int = MAX_LINKED_ISSUES,
) -> tuple[list[IssueRef], int]:
    """Parse several texts (PR body first, then commit messages).

    Returns ``(issues, dropped)`` where ``issues`` has at most ``limit`` unique
    references and ``dropped`` counts the unique ones beyond the cap.
    """
    seen: set[tuple[str, str, int]] = set()
    ordered: list[IssueRef] = []
    for text in texts:
        for ref in parse_closing_references(
            text, default_owner=default_owner, default_repo=default_repo
        ):
            if ref.key not in seen:
                seen.add(ref.key)
                ordered.append(ref)
    return ordered[:limit], max(0, len(ordered) - limit)


def _blank_inline_code(text: str) -> str:
    """Blank ``code`` spans: a backtick run closes at the next run of equal length.

    Linear time (a regex with a backreference is quadratic on long backtick runs).
    """
    runs = [(m.start(), m.end()) for m in _BACKTICK_RUN.finditer(text)]
    if len(runs) < 2:
        return text
    following: list[int | None] = [None] * len(runs)
    last_seen: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        width = runs[index][1] - runs[index][0]
        following[index] = last_seen.get(width)
        last_seen[width] = index
    pieces: list[str] = []
    cursor = 0
    index = 0
    while index < len(runs):
        close = following[index]
        if close is None:
            index += 1
            continue
        start, end = runs[index][0], runs[close][1]
        pieces.append(text[cursor:start])
        pieces.append(_blank_text(text[start:end]))
        cursor = end
        index = close + 1
    pieces.append(text[cursor:])
    return "".join(pieces)


def _blank(match: re.Match[str]) -> str:
    return _blank_text(match.group(0))


def _blank_text(text: str) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in text)


__all__ = [
    "MAX_LINKED_ISSUES",
    "IssueRef",
    "collect_linked_issues",
    "parse_closing_references",
    "strip_ignored_regions",
]
