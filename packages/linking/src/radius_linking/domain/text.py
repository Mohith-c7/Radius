"""Pure text helpers: identifier splitting, tokenization, stopwords, light stemming.

Deterministic, stdlib only, Unicode aware. Used by every linker so that
``applyDiscount``, ``apply_discount`` and "apply discount" meet in one token space.
"""

from __future__ import annotations

import re
import unicodedata

_CAMEL = re.compile(r"(?<=[a-z0-9ß-ÿ])(?=[A-ZÀ-Þ])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_WORD_LIKE = re.compile(r"[^\W_][\w]*", re.UNICODE)

PROSE_STOPWORDS = frozenset(
    """a an the and or but nor of in on at to for from by with without within into onto over
    under as is are was were be been being am do does did done doing has have had having it its
    this that these those there here then than so such not no yes can could may might must
    shall should will would which who whom whose what when where why how if else also only any
    all each every both either neither some more most less least very just per via etc
    ie eg i we you they he she them our your their his her me my us one two
    returns return given new""".split()
)
"""Prose function words (and generic criterion verbs) that carry no linking signal."""

CODE_STOPWORDS = frozenset(
    """self cls this def class function func fn return returns import from as pass none null nil
    true false undefined var let const val int str string bool float list dict set tuple any
    object void async await lambda yield raise try except finally catch throw new if else elif
    for while in is not and or with del global nonlocal assert break continue public private
    protected static final export default type interface enum module""".split()
)
"""Language keywords / ubiquitous builtins that are noise inside symbol documents."""


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def split_identifier(name: str) -> list[str]:
    """Split ``camelCase``, ``PascalCase``, ``snake_case``, ``kebab-case``, ``HTTPServer2``.

    Lowercased (casefold), digits stay attached to the preceding letters
    (``http2`` stays one token), empty parts dropped.
    """

    out: list[str] = []
    for chunk in _NON_WORD.split(normalize(name)):
        if not chunk:
            continue
        for part in _CAMEL.split(chunk):
            if part:
                out.append(part.casefold())
    return out


def stem(token: str) -> str:
    """Very light, deterministic suffix stripping (plural / -ing / -ed)."""

    t = token
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("sses"):
        return t[:-2]
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
        if len(t) > 2 and t[-1] == t[-2] and t[-1] not in "ls":
            t = t[:-1]
        return t
    if len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
        if len(t) > 2 and t[-1] == t[-2] and t[-1] not in "ls":
            t = t[:-1]
        return t
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def terms(
    text: str, *, stop: frozenset[str] = PROSE_STOPWORDS, do_stem: bool = True
) -> list[str]:
    """Content terms of prose or code text: identifier-split, stopped, stemmed.

    Order and multiplicity are preserved (BM25 needs term frequencies).
    """

    out: list[str] = []
    for word in _WORD_LIKE.findall(normalize(text)):
        for part in split_identifier(word):
            if part in stop or len(part) < 2 and not part.isdigit():
                continue
            out.append(stem(part) if do_stem else part)
    return out


def code_terms(text: str) -> list[str]:
    """Terms of code-ish text (names, signatures, bodies): code + prose stopwords removed."""

    return terms(text, stop=CODE_STOPWORDS | PROSE_STOPWORDS)


def name_terms(name: str) -> list[str]:
    """Stemmed terms of an identifier or qualified name, keeping short parts."""

    return [stem(t) for t in split_identifier(name) if t]
