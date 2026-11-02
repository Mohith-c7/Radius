"""Shared building blocks of the language indexers (LK-01)."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

# Re-exported so indexers and F-08 agree on the module pseudo-symbol name.
from radius_graph.symbol_impact import MODULE_SYMBOL  # noqa: F401

_SHINGLE = 3
_MAX_SIMILARITY_TOKENS = 20000


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]  # noqa: S324


def tokens_hash(tokens: list[str] | tuple[str, ...]) -> str:
    return short_hash("\x1f".join(tokens))


@dataclass(slots=True)
class Defn:
    """One definition found in one version of a file.

    ``body`` holds the *own* body tokens: nested definitions are omitted,
    comments and docstrings are removed, so a change
    inside a method never modifies its class. ``match_tokens`` additionally
    contains the children (used only for rename/move similarity).
    """

    qualname: str
    kind: str
    start: int
    end: int
    signature: str  # name-free normalised signature
    display: str  # human readable signature including the name
    body: tuple[str, ...]
    decorators: tuple[str, ...] = ()
    docstring: str | None = None
    parent: int | None = None  # index into FileIndex.defs
    base_qualname: str = ""  # qualname before ``@N`` de-duplication
    match_tokens: list[str] = field(default_factory=list)
    _shingles: Counter | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.qualname, self.kind)

    @property
    def last_name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1].split("@", 1)[0]

    @property
    def parent_name(self) -> str:
        head, _, _ = self.qualname.rpartition(".")
        return head

    @property
    def signature_hash(self) -> str:
        return short_hash(self.signature)

    @property
    def body_hash(self) -> str:
        return tokens_hash(self.body)

    def shingles(self) -> Counter:
        if self._shingles is None:
            toks = self.match_tokens[:_MAX_SIMILARITY_TOKENS]
            if len(toks) < _SHINGLE:
                self._shingles = Counter(["\x1f".join(toks)]) if toks else Counter()
            else:
                self._shingles = Counter(
                    "\x1f".join(toks[i : i + _SHINGLE]) for i in range(len(toks) - _SHINGLE + 1)
                )
        return self._shingles


def similarity(a: Defn, b: Defn) -> float:
    """Multiset-Jaccard of token 3-grams of signature+body, in ``[0, 1]``."""

    sa, sb = a.shingles(), b.shingles()
    if not sa or not sb:
        return 0.0
    union = (sa | sb).total()
    return round((sa & sb).total() / union, 6) if union else 0.0


@dataclass(slots=True)
class FileIndex:
    """Definitions and line facts of one version of one file."""

    language: str
    line_count: int
    defs: list[Defn] = field(default_factory=list)
    import_lines: set[int] = field(default_factory=set)
    # (start_line, end_line, text) of every comment, in source order
    comments: list[tuple[int, int, str]] = field(default_factory=list)
    module_index: int | None = None  # defs index of the <module> pseudo-symbol
    parse_error: str | None = None


def dedupe_qualnames(defs: list[Defn]) -> None:
    """Make (qualname, kind) unique: later duplicates get ``@2``, ``@3`` ..."""

    seen: Counter = Counter()
    for d in sorted(defs, key=lambda x: (x.start, -x.end)):
        d.base_qualname = d.qualname
        seen[d.key] += 1
        if seen[d.key] > 1:
            d.qualname = f"{d.qualname}@{seen[d.key]}"


def link_children(defs: list[Defn]) -> None:
    """Fill ``match_tokens`` (own tokens + signature + descendants, in order)."""

    for d in defs:
        d.match_tokens = [*d.signature.split(), *d.body]
    for idx in sorted(range(len(defs)), key=lambda i: (defs[i].start, -defs[i].end), reverse=True):
        parent = defs[idx].parent
        if parent is not None:
            defs[parent].match_tokens.extend(defs[idx].match_tokens)


def paint_owners(defs: list[Defn], line_count: int) -> list[int]:
    """Return ``owner[line] -> defs index`` (``-1`` none) for lines ``1..line_count``.

    The module pseudo-symbol is not painted: lines owned by nobody are
    module-level. Inner definitions overwrite outer ones.
    """

    owner = [-1] * (line_count + 2)
    order = sorted(
        (i for i, d in enumerate(defs) if d.kind != "module"),
        key=lambda i: (defs[i].start, -defs[i].end),
    )
    for i in order:
        d = defs[i]
        lo, hi = max(d.start, 1), min(d.end, line_count)
        if hi >= lo:
            owner[lo : hi + 1] = [i] * (hi - lo + 1)
    return owner
