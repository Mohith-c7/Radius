"""Escaping of untrusted text for GitHub-flavoured Markdown (VD-06, risk R5).

Criterion text, test names, file paths, tamper reasons and snippets come from a
pull request and must never be able to: ping users (``@name``, ``@org/team``),
create links, images, autolinks or issue references, inject HTML or comments,
break out of a table cell or code span, hide content with zero-width or bidi
characters, or blow up the comment size. Two renderers cover every use:

* ``code(text)``: a single-line inline code span (safe in table cells).
* ``plain(text)``: flowing text with Markdown metacharacters backslash-escaped
  and risky tokens (mentions, issue refs, URLs, e-mail addresses) wrapped in
  inline code, which GitHub does not turn into notifications or links.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata

DEFAULT_MAX_LEN = 140
ELLIPSIS = "..."

#: Unicode categories removed outright: controls, format (zero-width, bidi),
#: surrogates, private use, unassigned. Newlines/tabs are flattened first.
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
#: Invisible letters/marks that survive the category filter (filler characters,
#: combining grapheme joiner, Mongolian free variation selectors, braille blank).
_INVISIBLE = frozenset(
    "͏ᅟᅠ឴឵⠀ㅤﾠ᠋᠌᠍᠎"
)
#: Separators that behave like line breaks.
_LINE_SEPARATORS = frozenset({"\n", "\r", "\t", "\v", "\f", "\u0085", " ", " "})
_WS = re.compile(r"\s+")

#: Tokens wrapped in inline code by ``plain``: URLs, e-mails, mentions, issue refs.
_RISKY = re.compile(
    r"""
    (?:[A-Za-z][A-Za-z0-9+.-]*://\S+)             # scheme://anything
    |(?:www\.\S+)                                 # www.host
    |(?:\S+@\S+\.\S+)                             # e-mail like
    |(?:@[A-Za-z0-9_][A-Za-z0-9_./-]*)            # @user, @org/team
    |(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\#\d+)     # owner/repo#123
    |(?:\bGH-\d+\b)                               # GH-123
    |(?:\#[A-Za-z0-9_-]+)                         # #123, #anchor
    """,
    re.VERBOSE,
)
#: Markdown metacharacters; ``_`` only at a word boundary (snake_case stays readable).
_MD_SPECIAL = re.compile(r"((?<![A-Za-z0-9])_|_(?![A-Za-z0-9])|[\\`*\[\]~|!{}])")
#: Characters outside a "safe token" (versions, rule ids, labels; no dot or slash).
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_:-]")
_SAFE_URL = re.compile(r"^https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+$")


def _escape_piece(piece: str) -> str:
    """Entity-encode ``& < >`` (the source never holds a raw ``<``), escape the rest."""

    piece = piece.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MD_SPECIAL.sub(r"\\\1", piece)


def clean(text: object, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Normalise untrusted text: strip invisible/control chars, flatten, cap length.

    Non-strings become ``""``. The result is a single line without leading or
    trailing whitespace, at most ``max_len`` characters (``...`` marks a cut).
    """

    if not isinstance(text, str):
        return ""
    out: list[str] = []
    for ch in text:
        if ch in _LINE_SEPARATORS:
            out.append(" ")
        elif ch in _INVISIBLE or unicodedata.category(ch) in _DROP_CATEGORIES:
            continue
        else:
            out.append(ch)
    flat = _WS.sub(" ", "".join(out)).strip()
    if len(flat) > max_len:
        keep = max(0, max_len - len(ELLIPSIS))
        flat = flat[:keep].rstrip() + ELLIPSIS
    return flat


def code(text: object, max_len: int = DEFAULT_MAX_LEN, *, empty: str = "(empty)") -> str:
    """Render ``text`` as one inline code span that cannot be broken out of.

    Backticks become apostrophes and ``|`` is escaped so table cells survive.
    """

    flat = clean(text, max_len).replace("`", "'").replace("|", "\\|")
    return f"`{flat or empty}`"


def plain(text: object, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Render ``text`` as flowing Markdown with all active syntax neutralised."""

    flat = clean(text, max_len)
    pieces: list[str] = []
    last = 0
    for match in _RISKY.finditer(flat):
        pieces.append(_escape_piece(flat[last : match.start()]))
        pieces.append(code(match.group(0), max_len=max_len))
        last = match.end()
    pieces.append(_escape_piece(flat[last:]))
    return "".join(pieces)


def token(text: object, max_len: int = 48, *, fallback: str = "unknown") -> str:
    """Restrict ``text`` to ``[A-Za-z0-9_:-]`` (ids, versions, rule ids).

    No ``.`` or ``/`` so a token can never form a URL, host name or path.
    """

    flat = _SAFE_TOKEN.sub("?", clean(text, max_len))
    return flat or fallback


def safe_url(value: object, max_len: int = 300) -> str | None:
    """Return ``value`` if it is a plain http(s) URL we are willing to link."""

    if not isinstance(value, str) or len(value) > max_len or not _SAFE_URL.match(value):
        return None
    return value


def short_sha(value: object) -> str:
    """First 7 hex characters of a commit sha, or ``unknown``."""

    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{7,40}", value):
        return value[:7]
    return "unknown"
