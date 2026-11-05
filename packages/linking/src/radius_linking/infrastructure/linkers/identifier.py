"""Identifier / phrase linker.

Extracts *anchors* from the criterion: code names (``apply_discount``,
``applyDiscount()``, backticked names), endpoint paths (``/api/v1/users/{id}``),
HTTP status codes, quoted error strings, CLI flags (``--dry-run``), config keys
(``MAX_RETRIES``, ``db.pool.size``), exception names and numeric literals.
Each anchor is matched exactly or fuzzily against the symbol's qualified name,
string literals, decorators (route decorators) and body identifiers.

Per anchor: ``score = weight(kind) * match_quality / (1 + 0.5 * (m - 1))`` where
``m`` is the number of symbols the anchor matches (a rare anchor is more
telling than ``ValueError`` found in half the diff). Anchors combine per symbol
with noisy-OR, capped at 0.92.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from radius_linking.domain import (
    LINKER_IDENTIFIER,
    CriterionInput,
    Link,
    LinkContext,
    Reason,
    SymbolDoc,
)
from radius_linking.domain.text import name_terms, normalize
from radius_linking.infrastructure.linkers.common import noisy_or, reason, sort_reasons

VERSION = "identifier-v1"
CAP = 0.92
KIND_WEIGHT = {
    "symbol_name": 0.9,
    "endpoint": 0.9,
    "error_string": 0.85,
    "flag": 0.85,
    "config_key": 0.8,
    "exception": 0.55,
    "status": 0.5,
    "number": 0.25,
}

_BACKTICK = re.compile(r"`([^`\n]{1,120})`")
_QUOTED = re.compile(r"\"([^\"\n]{3,120})\"|'([^'\n]{3,120})'|“([^”\n]{3,120})”")
_ENDPOINT = re.compile(
    r"(?:(?<=\s)|(?<=^)|(?<=[`\"'(]))(/[A-Za-z0-9_{}:<>.\-]+(?:/[A-Za-z0-9_{}:<>.\-]*)*)"
)
_FLAG = re.compile(r"(?<![\w-])(--[A-Za-z][\w-]*)")
_CONST = re.compile(r"\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b")
_DOTTED = re.compile(r"\b([a-z][a-z0-9_-]+(?:\.[a-z][a-z0-9_-]+)+)\b")
_EXC = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception))\b")
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\(\)")
_SNAKE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)\b")
_CAMEL = re.compile(
    r"\b([a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"
)
_STATUS = re.compile(
    r"(?i)\b(?:status(?: code)?|http|code|respond(?:s|ing)? with|response|returns?|raises?)"
    r"\W{0,3}([1-5]\d\d)\b"
)
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
_PARAM = re.compile(r"\{[^}/]*\}|<[^>/]*>|(?<=/):[A-Za-z_]\w*")
_FILE_EXT = re.compile(
    r"\.(?:py|pyi|ts|tsx|js|jsx|go|java|rb|rs|cs|php|md|json|ya?ml|toml|txt|cfg|ini|lock)$"
)


@dataclass(frozen=True)
class Anchor:
    kind: str
    text: str

    @property
    def weight(self) -> float:
        return KIND_WEIGHT[self.kind]


def _classify_backtick(raw: str) -> list[Anchor]:
    t = raw.strip()
    if not t:
        return []
    if t.startswith("/") and len(t) > 1:
        return [Anchor("endpoint", t)]
    if t.startswith("--") and len(t) > 2:
        return [Anchor("flag", t)]
    if _EXC.fullmatch(t):
        return [Anchor("exception", t)]
    if t.isdigit() and len(t) == 3 and t[0] in "12345":
        return [Anchor("status", t)]
    if " " in t:
        return [Anchor("error_string", t)]
    if _CONST.fullmatch(t) or ("." in t and not _FILE_EXT.search(t) and t[0].islower()):
        return [Anchor("config_key", t)]
    t = t.removesuffix("()")
    return [Anchor("symbol_name", t)] if len(t) >= 2 and not t.isdigit() else []


def extract_anchors(text: str, *, max_anchors: int = 40) -> list[Anchor]:
    """Deterministic, de-duplicated anchors of a criterion text (at most ``max_anchors``)."""

    text = normalize(text)
    found: dict[tuple[str, str], Anchor] = {}

    def add(anchor: Anchor) -> None:
        found.setdefault((anchor.kind, anchor.text.casefold()), anchor)

    for m in _BACKTICK.finditer(text):
        for a in _classify_backtick(m.group(1)):
            add(a)
    stripped = _BACKTICK.sub(" ", text)
    for m in _QUOTED.finditer(stripped):
        add(Anchor("error_string", next(g for g in m.groups() if g).strip()))
    stripped = _QUOTED.sub(" ", stripped)
    for m in _ENDPOINT.finditer(stripped):
        ep = m.group(1).rstrip(".,;:)")
        if len(ep) > 1 and not _FILE_EXT.search(ep):
            add(Anchor("endpoint", ep))
    for m in _FLAG.finditer(stripped):
        add(Anchor("flag", m.group(1)))
    for m in _EXC.finditer(stripped):
        add(Anchor("exception", m.group(1)))
    for m in _STATUS.finditer(stripped):
        add(Anchor("status", m.group(1)))
    for m in _CONST.finditer(stripped):
        add(Anchor("config_key", m.group(1)))
    for m in _DOTTED.finditer(stripped):
        parts = m.group(1).split(".")
        if all(len(p) >= 2 for p in parts) and not _FILE_EXT.search(m.group(1)):
            add(Anchor("config_key", m.group(1)))
    for rx in (_CALL, _SNAKE, _CAMEL):
        for m in rx.finditer(stripped):
            tok = m.group(1)
            key = tok.casefold()
            if ("config_key", key) not in found and ("exception", key) not in found:
                add(Anchor("symbol_name", tok))
    statuses = {a.text for a in found.values() if a.kind == "status"}
    for m in _NUMBER.finditer(stripped):
        if m.group(1) not in statuses:
            add(Anchor("number", m.group(1)))
    return list(found.values())[:max_anchors]


def _norm_str(s: str) -> str:
    return " ".join(normalize(s).casefold().split())


def _norm_endpoint(s: str) -> str:
    return _PARAM.sub("{}", s.strip().casefold()).rstrip("/") or "/"


def _name_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = name_terms(anchor)
    if not a:
        return 0.0, ""
    simple, qual = name_terms(sym.simple_name), name_terms(sym.qualified_name)
    if a == simple or a == qual:
        return 1.0, f"exact name {sym.qualified_name}"
    if len(a) >= 2 and set(a) <= set(qual):
        return 0.75, f"name tokens contained in {sym.qualified_name}"
    if len(a) == 1 and len(a[0]) >= 4 and a[0] in qual and len(qual) > 1:
        return 0.35, f"part of name {sym.qualified_name}"
    joined = " ".join(a)
    for cand in (" ".join(simple), " ".join(qual)):
        if len(joined) >= 5 and len(cand) >= 5:
            ratio = SequenceMatcher(None, joined, cand).ratio()
            if ratio >= 0.8:
                return (
                    0.7 * ratio,
                    f"fuzzy name match {sym.qualified_name} ({ratio:.2f})",
                )
    for ident in sym.identifiers:
        if name_terms(ident) == a:
            return 0.5, f"identifier '{ident}' used in body"
    for lit in sym.literals:
        if name_terms(lit) == a:
            return 0.4, f"string literal '{lit[:40]}'"
    return 0.0, ""


def _string_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = _norm_str(anchor)
    a_tok = set(name_terms(anchor))
    best, why = 0.0, ""
    for lit in sym.literals:
        n = _norm_str(lit)
        if not n:
            continue
        if n == a:
            return 1.0, f"literal '{lit[:60]}'"
        q = 0.0
        if len(n) >= 6 and (n in a or a in n):
            q = 0.75
        else:
            l_tok = set(name_terms(lit))
            if len(l_tok) >= 2 and a_tok:
                jac = len(a_tok & l_tok) / len(a_tok | l_tok)
                if jac >= 0.6:
                    q = 0.8 * jac
        if q > best:
            best, why = q, f"similar literal '{lit[:60]}'"
    return best, why


def _endpoint_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = _norm_endpoint(anchor)
    best, why = 0.0, ""
    for lit in (*sym.literals, *sym.decorators):
        for seg in re.findall(r"/[^\s'\"`)]*", lit):
            n = _norm_endpoint(seg)
            if n == a:
                return 1.0, f"route/literal {seg[:60]}"
            if len(n) > 1 and (n.endswith(a) or a.endswith(n)) and best < 0.8:
                best, why = 0.8, f"route/literal {seg[:60]} overlaps"
    return best, why


def _flag_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = anchor.casefold()
    for lit in (*sym.literals, *sym.decorators):
        if a in lit.casefold():
            return 1.0, f"flag literal {anchor}"
    a_tok = name_terms(anchor)
    for ident in sym.identifiers:
        if name_terms(ident) == a_tok:
            return 0.7, f"identifier '{ident}' for flag {anchor}"
    return 0.0, ""


def _config_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = anchor.casefold()
    for lit in sym.literals:
        if lit.casefold() == a:
            return 1.0, f"literal key '{lit[:60]}'"
    if name_terms(sym.simple_name) == name_terms(anchor):
        return 1.0, f"symbol {sym.qualified_name} is the key"
    for ident in sym.identifiers:
        if ident.casefold() == a or name_terms(ident) == name_terms(anchor):
            return 0.85, f"identifier '{ident}'"
    last = name_terms(anchor.rsplit(".", 1)[-1])
    if last:
        for ident in sym.identifiers:
            if name_terms(ident) == last:
                return 0.45, f"identifier '{ident}' matches last key segment"
    return 0.0, ""


def _exception_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    a = anchor.casefold()
    for ident in sym.identifiers:
        if ident.casefold() == a:
            return 1.0, f"uses {ident}"
    if name_terms(sym.simple_name) == name_terms(anchor):
        return 1.0, f"defines {sym.qualified_name}"
    return 0.0, ""


def _status_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    if anchor in sym.literals:
        return 1.0, f"literal {anchor}"
    for ident in sym.identifiers:
        if anchor in name_terms(ident):
            return 0.9, f"identifier '{ident}'"
    return 0.0, ""


def _number_match(anchor: str, sym: SymbolDoc) -> tuple[float, str]:
    for lit in sym.literals:
        try:
            if float(lit) == float(anchor):
                return 1.0, f"numeric literal {lit}"
        except ValueError:
            continue
    return 0.0, ""


_MATCHERS = {
    "symbol_name": _name_match,
    "error_string": _string_match,
    "endpoint": _endpoint_match,
    "flag": _flag_match,
    "config_key": _config_match,
    "exception": _exception_match,
    "status": _status_match,
    "number": _number_match,
}


class IdentifierLinker:
    name = LINKER_IDENTIFIER
    version = VERSION

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]:
        links: list[Link] = []
        for crit in criteria:
            anchors = extract_anchors(crit.text)
            per_symbol: dict[str, list[Reason]] = {}
            for anchor in anchors:
                hits = []
                for sym in symbols:
                    q, why = _MATCHERS[anchor.kind](anchor.text, sym)
                    if q > 0:
                        hits.append((sym.symbol_id, q, why))
                rarity = 1.0 / (1.0 + 0.5 * (len(hits) - 1)) if hits else 1.0
                for symbol_id, q, why in hits:
                    per_symbol.setdefault(symbol_id, []).append(
                        reason(
                            self.name,
                            anchor.kind,
                            f"anchor '{anchor.text[:60]}': {why}",
                            anchor.weight * q * rarity,
                        )
                    )
            for symbol_id, reasons in per_symbol.items():
                score = min(CAP, noisy_or([r.score for r in reasons]))
                links.append(
                    Link(
                        crit.criterion_id,
                        symbol_id,
                        self.name,
                        score,
                        sort_reasons(reasons),
                    )
                )
        return links
