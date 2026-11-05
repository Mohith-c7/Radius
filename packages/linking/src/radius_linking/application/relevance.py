"""Criterion -> test relevance ``r_ct`` (VS-04, ``criterion-test-relevance-v1``).

LK-03 links a symbol to its tests; when one function implements several criteria,
every test of that function would otherwise support every criterion (finding F4 of
``VERDICT_V2_SLICE.md``). ``r_ct`` estimates how relevant a test is to THAT
criterion, in [0, 1], from independent, deterministic, explainable signals:

1. ``lexical_overlap``   normalised BM25 of the criterion terms against the test
   document (name x3, docstring x2, parametrize ids, assertion expected values x2,
   assertion subjects, exception types x2, asserted names, literals). Terms that
   only name the connecting symbol are removed from the query: they explain the
   symbol link, not the criterion link.
2. ``assertion_subject`` / ``exception_match``  anchors in the criterion (exception
   names, status codes, quoted strings, numbers, code identifiers) found in what the
   assertions check; an exception assertion for a criterion about errors.
3. ``explicit_hint``     a ``tests`` hint of ``.radius/intent.yml`` gives 1.0 and is
   exempt from the penalties.
4. ``name_convention``   the ``test_<behavior>`` name (symbol terms removed, verbs
   canonicalised) is covered by the criterion words.
5. ``specificity_penalty`` a test strongly related to many criteria is less specific.
6. negative signals ``behavior_mismatch``, ``exception_type_mismatch``,
   ``asserts_other_symbols`` multiply the score by a factor < 1.

Rule (monotone in every signal; the factors only lower the score)::

    fired   = {i : s_i >= signal_floor}              none fired -> r_ct = 0.0 (gate)
    pos     = 1 - prod_{i fired} (1 - w_i * s_i)     w: assertion .9, lexical .7, name .6
    r0      = pos * prod(negative factors)
    r_ct    = r0 * specificity(test)                 below r_floor -> 0.0
    hint    -> r_ct = 1.0

Pure function of its inputs: no clock, network, randomness or LLM.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_linking.domain.bm25 import BM25Index
from radius_linking.domain.chain import SymbolTestEdge
from radius_linking.domain.model import COMBINED, CriterionInput, Link
from radius_linking.domain.relevance import (
    R_ASSERTION,
    R_BEHAVIOR,
    R_BELOW_FLOOR,
    R_EXC_TYPE,
    R_EXCEPTION,
    R_HINT,
    R_LEXICAL,
    R_NAME,
    R_NO_SIGNAL,
    R_OTHER_SYMBOLS,
    R_SPECIFICITY,
    RELEVANCE_ALGO_VERSION,
    CriterionTestRelevance,
    RelevanceReason,
    RelevanceSet,
    TestDoc,
)
from radius_linking.domain.text import CODE_STOPWORDS, PROSE_STOPWORDS, stem, terms

# ----------------------------------------------------------------------------- vocabulary

_NUMBER_WORDS = {
    "zero": "0", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "hundred": "100", "thousand": "1000",
}  # fmt: skip
"""``one``/``two`` are prose stopwords and never become terms."""

_SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "reject": tuple(
        (
            "reject raise rais error exception invalid fail refuse deny throw forbid "
            "disallow unauthorized"
        ).split()
    ),
    "accept": tuple("accept allow valid succeed permit".split()),
    "strip": tuple("strip trim whitespace blank".split()),
    "boundary": tuple("max min limit boundary".split()),
}
_CANON: dict[str, str] = {}
for _canon_name, _members in _SYNONYM_GROUPS.items():
    for _member in _members:
        _CANON[stem(_member)] = _canon_name
        _CANON[_member] = _canon_name
for _word, _digits in list(_NUMBER_WORDS.items()):
    _NUMBER_WORDS.setdefault(stem(_word), _digits)
_CANON_REJECT = "reject"
_CONSTRAINT_WORDS = frozenset(
    "need require least most must only within between outside above below max min "
    "limit exceed maximum minimum".split()
)
_CONSTRAINT_CANON = frozenset(
    set(_CONSTRAINT_WORDS) | {stem(w) for w in _CONSTRAINT_WORDS} | {"boundary"}
)

_EXC_NAME = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:Error|Exception|Exit)\b")
_CAMEL_NAME = re.compile(r"\b(?:[A-Z][a-z0-9]+){2,}\b")
_QUOTED = re.compile(r"`([^`]{1,60})`|'([^']{1,60})'|\"([^\"]{1,60})\"")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_STATUS_ANY = re.compile(r"(?<![\w.])([2-5]\d\d)(?![\w])")
_STATUS_CTX = re.compile(r"\b(status|http|code|respon\w*)\b", re.IGNORECASE)
_CODE_IDENT = re.compile(
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b[a-z]+(?:[A-Z][a-z0-9]+)+\b"
)


def _canon(term: str) -> str:
    return _CANON.get(term, _NUMBER_WORDS.get(term, term))


def canonical_terms(text: str) -> list[str]:
    """``terms`` plus synonym/number-word canonicalisation (shared by signals 1 and 4)."""

    return [_canon(t) for t in terms(text)]


def _name_terms(name: str) -> list[str]:
    body = re.sub(r"(?i)^test(?=[A-Z_])", "", name)
    body = body[1:] if body.startswith("_") else body
    return [_canon(t) for t in terms(body, stop=PROSE_STOPWORDS | CODE_STOPWORDS)]


def _symbol_terms(symbol_ids: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for sid in symbol_ids:
        _, _, qual = sid.rpartition("::")
        out.update(terms(qual.replace(".", " ")))
    return frozenset(out)


def _symbol_last_names(symbol_ids: Iterable[str]) -> frozenset[str]:
    return frozenset(
        s.rpartition("::")[2].rsplit(".", 1)[-1].casefold() for s in symbol_ids if s
    )


# ----------------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class RelevanceConfig:
    """Every constant of the rule; recorded in ``RelevanceSet.config``."""

    signal_floor: float = 0.1
    r_floor: float = 0.05
    w_assertion: float = 0.9
    w_lexical: float = 0.7
    w_name: float = 0.6
    lexical_scale: float = 1.5
    exception_agreement: float = 0.4
    behavior_mismatch_factor: float = 0.25
    success_mismatch_factor: float = 0.6
    exception_type_factor: float = 0.3
    other_symbols_factor: float = 0.3
    specificity_free: int = 2
    specificity_slope: float = 0.15
    specificity_min: float = 0.5
    specificity_count_threshold: float = 0.3
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    def __post_init__(self) -> None:
        for name in (
            "signal_floor", "r_floor", "w_assertion", "w_lexical", "w_name",
            "exception_agreement", "behavior_mismatch_factor", "success_mismatch_factor",
            "exception_type_factor", "other_symbols_factor", "specificity_min",
            "specificity_count_threshold",
        ):  # fmt: skip
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if (
            self.lexical_scale <= 0
            or self.specificity_slope < 0
            or self.specificity_free < 0
        ):
            raise ValueError("invalid lexical_scale / specificity parameters")

    def to_dict(self) -> dict[str, Any]:
        return {n: getattr(self, n) for n in self.__slots__}


# ----------------------------------------------------------------------------- criterion facets


@dataclass(frozen=True, slots=True)
class CriterionFacets:
    """Matchable anchors and behaviour class of one criterion."""

    terms: frozenset[str]
    error_class: bool
    constraint: bool
    exceptions: tuple[str, ...]
    statuses: tuple[str, ...]
    quoted: tuple[str, ...]
    numbers: tuple[str, ...]
    identifiers: tuple[str, ...]

    @property
    def has_anchors(self) -> bool:
        return bool(
            self.exceptions
            or self.statuses
            or self.quoted
            or self.numbers
            or self.identifiers
        )


def criterion_facets(
    text: str, symbol_names: frozenset[str] = frozenset()
) -> CriterionFacets:
    """Extract anchors and the behaviour class from criterion text (deterministic)."""

    cset = frozenset(canonical_terms(text))
    exc_names = {m.casefold() for m in _EXC_NAME.findall(text)}
    if (
        _CANON_REJECT in cset
    ):  # a CamelCase name next to an error verb is an exception type
        exc_names |= {m.casefold() for m in _CAMEL_NAME.findall(text)}
    exceptions = tuple(sorted(exc_names))
    statuses = {m for m in _STATUS_ANY.findall(text) if m[0] in "45"}
    if _STATUS_CTX.search(text):
        statuses |= set(_STATUS_ANY.findall(text))
    quoted = sorted(
        {
            q.casefold()
            for m in _QUOTED.findall(text)
            for q in m
            if q and any(c.isalnum() for c in q) and " " not in q.strip()
        }
    )
    numbers = tuple(
        sorted(
            ({n for n in _NUMBER.findall(text)} | {c for c in cset if c.isdigit()})
            - statuses
        )
    )
    idents = tuple(
        sorted(
            {i.casefold() for i in _CODE_IDENT.findall(text)}
            - symbol_names
            - set(quoted)
        )
    )
    error_class = (
        _CANON_REJECT in cset or bool(exceptions) or any(s[0] in "45" for s in statuses)
    )
    return CriterionFacets(
        cset,
        error_class,
        bool(cset & _CONSTRAINT_CANON),
        exceptions,
        tuple(sorted(statuses)),
        tuple(quoted),
        numbers,
        idents,
    )


# ----------------------------------------------------------------------------- test side


def _test_pool(doc: TestDoc) -> str:
    parts: list[str] = list(doc.param_ids) + list(doc.literals)
    for a in doc.assertions:
        parts += [a.subject, a.expected, a.exception_type, *a.symbol_names]
    return "\n".join(p for p in parts if p).casefold()


def _test_error_class(doc: TestDoc, name_terms: Sequence[str]) -> bool:
    return any(a.is_exception for a in doc.assertions) or _CANON_REJECT in name_terms


def _bm25_tokens(doc: TestDoc) -> Counter[str]:
    c: Counter[str] = Counter()

    def add(text: str, w: int, *, code: bool = False) -> None:
        toks = (
            [_canon(t) for t in terms(text, stop=PROSE_STOPWORDS | CODE_STOPWORDS)]
            if code
            else canonical_terms(text)
        )
        for t in toks:
            c[t] += w

    for t in _name_terms(doc.name):
        c[t] += 3
    add(doc.docstring, 2)
    for p in doc.param_ids:
        add(p, 1, code=True)
    for lit in doc.literals:
        add(lit, 1, code=True)
    for a in doc.assertions:
        add(a.subject, 1, code=True)
        add(a.expected, 2, code=True)
        add(a.exception_type, 2, code=True)
        for n in a.symbol_names:
            add(n, 1, code=True)
    return c


# ----------------------------------------------------------------------------- signals


@dataclass(frozen=True, slots=True)
class Signal:
    """One positive signal and its score in [0, 1]."""

    code: str
    score: float
    detail: str


def lexical_signal(
    index: BM25Index,
    doc_id: str,
    facets: CriterionFacets,
    symbol_terms: frozenset[str],
    scale: float,
) -> Signal:
    """Signal 1: normalised BM25, ``sum(term score) / sum(per-term ceiling)`` times ``scale``."""

    query = sorted(t for t in facets.terms if t not in symbol_terms)
    if not query:
        return Signal(
            R_LEXICAL, 0.0, "no criterion terms left after removing symbol terms"
        )
    got = index.term_scores(query, doc_id)
    ceiling = sum(index.max_term_score(t) for t in query)
    raw = sum(got.values()) / ceiling if ceiling else 0.0
    matched = ",".join(sorted(got)) or "-"
    return Signal(
        R_LEXICAL, min(1.0, raw * scale), f"matched {matched} of {len(query)} terms"
    )


_ANCHOR_WEIGHTS = {
    "exception": 1.0,
    "status": 1.0,
    "quoted": 1.0,
    "identifier": 0.7,
    "number": 0.5,
}


def _exc_match(wanted: str, have: str) -> bool:
    return bool(wanted) and bool(have) and (wanted in have or have in wanted)


def assertion_signal(
    doc: TestDoc, facets: CriterionFacets, cfg: RelevanceConfig
) -> tuple[Signal, Signal]:
    """Signal 2: anchors found in the assertions, and exception agreement.

    Returns ``(assertion_subject, exception_match)``; either may score 0.
    """

    pool = _test_pool(doc)
    pool_numbers = set(_NUMBER.findall(pool)) | set(_STATUS_ANY.findall(pool))
    exc_types = [
        a.exception_type.casefold() for a in doc.assertions if a.exception_type
    ]
    total = got = 0.0
    hits: list[str] = []

    def take(kind: str, anchor: str, ok: bool) -> None:
        nonlocal total, got
        w = _ANCHOR_WEIGHTS[kind]
        total += w
        if ok:
            got += w
            hits.append(anchor)

    for e in facets.exceptions:
        take("exception", e, any(_exc_match(e, t) for t in exc_types) or e in pool)
    for s in facets.statuses:
        take("status", s, s in pool_numbers)
    for q in facets.quoted:
        take("quoted", q, q in pool)
    for n in facets.numbers:
        take("number", n, n in pool_numbers)
    for i in facets.identifiers:
        take("identifier", i, i in pool)
    anchor = Signal(
        R_ASSERTION,
        got / total if total else 0.0,
        f"anchors matched: {','.join(hits)}"
        if hits
        else "no criterion anchor in assertions",
    )
    exc = Signal(
        R_EXCEPTION, 0.0, "criterion not about an error, or no exception assertion"
    )
    if facets.error_class and any(a.is_exception for a in doc.assertions):
        typed = any(_exc_match(e, t) for e in facets.exceptions for t in exc_types)
        exc = Signal(
            R_EXCEPTION,
            1.0 if typed else cfg.exception_agreement,
            "exception type matches"
            if typed
            else "exception asserted for an error criterion",
        )
    return anchor, exc


def name_signal(
    doc: TestDoc, facets: CriterionFacets, symbol_terms: frozenset[str]
) -> Signal:
    """Signal 4: share of the test-name behaviour words (symbol terms removed) in the criterion."""

    words = [t for t in _name_terms(doc.name) if t not in symbol_terms]
    if not words:
        return Signal(
            R_NAME, 0.0, "test name has no behaviour words beyond the symbol name"
        )
    hit = sorted({w for w in words if w in facets.terms})
    return Signal(
        R_NAME,
        len(hit) / len(words),
        f"{len(hit)}/{len(words)} name words in criterion: {','.join(hit) or '-'}",
    )


def hint_matches(hint: str, test_id: str) -> bool:
    """A ``tests`` hint names a test id, a bare test name, or a test file (all its tests)."""

    h = hint.strip().replace("\\", "/")
    if not h:
        return False
    tid = test_id.replace("\\", "/")
    file_part = tid.split("::", 1)[0]
    return (
        (file_part == h or file_part.endswith("/" + h))
        or tid == h
        or tid.endswith("::" + h)
        or tid.startswith(h + "::")
        or tid.endswith("/" + h)
    )


# ----------------------------------------------------------------------------- connections


def connected_pairs(
    c2s_links: Iterable[Link],
    s2t_edges: Iterable[SymbolTestEdge],
    *,
    min_c2s: float = 0.0,
    min_s2t: float = 0.0,
) -> dict[tuple[str, str], tuple[str, ...]]:
    """``(criterion_id, test_id) -> symbol ids`` for pairs connected through a symbol.

    Uses the ``combined`` criterion -> symbol links (``LinkSet.links``) and the
    symbol -> test edges (LK-03 ``combined``). Order independent.
    """

    by_symbol: dict[str, set[str]] = {}
    for e in s2t_edges:
        if e.score > min_s2t and e.linker == COMBINED:
            by_symbol.setdefault(e.symbol_id, set()).add(e.test_id)
    out: dict[tuple[str, str], set[str]] = {}
    for link in c2s_links:
        if link.linker != COMBINED or link.score <= min_c2s:
            continue
        for tid in by_symbol.get(link.symbol_id, ()):
            out.setdefault((link.criterion_id, tid), set()).add(link.symbol_id)
    return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


# ----------------------------------------------------------------------------- scoring


def specificity_factor(n_criteria: int, cfg: RelevanceConfig) -> float:
    """``max(spec_min, 1 / (1 + slope * max(0, n - free)))`` (same shape as the LK-06 chain)."""

    return max(
        cfg.specificity_min,
        1.0 / (1.0 + cfg.specificity_slope * max(0, n_criteria - cfg.specificity_free)),
    )


@dataclass(frozen=True, slots=True)
class _Pre:
    criterion_id: str
    test_id: str
    symbols: tuple[str, ...]
    r0: float
    reasons: tuple[RelevanceReason, ...]
    hinted: bool
    fired: bool


def _score_pair(
    crit: CriterionInput,
    doc: TestDoc,
    symbols: tuple[str, ...],
    index: BM25Index,
    cfg: RelevanceConfig,
) -> _Pre:
    cid, tid = crit.criterion_id, doc.test_id
    if any(hint_matches(h, tid) for h in crit.tests):
        why = RelevanceReason(R_HINT, "test named in the criterion's tests hint", 1.0)
        return _Pre(cid, tid, symbols, 1.0, (why,), True, True)
    sym_terms = _symbol_terms(symbols)
    facets = criterion_facets(crit.text, _symbol_last_names(symbols))
    lex = lexical_signal(index, tid, facets, sym_terms, cfg.lexical_scale)
    anchor, exc = assertion_signal(doc, facets, cfg)
    name = name_signal(doc, facets, sym_terms)
    signals = [
        (anchor, cfg.w_assertion),
        (exc, cfg.w_assertion),
        (lex, cfg.w_lexical),
        (name, cfg.w_name),
    ]
    reasons: list[RelevanceReason] = []
    miss = 1.0
    for sig, w in signals:
        if sig.score > 0.0 and sig.score >= cfg.signal_floor:
            miss *= 1.0 - w * sig.score
            reasons.append(RelevanceReason(sig.code, sig.detail, sig.score))
    if not reasons:
        why = RelevanceReason(R_NO_SIGNAL, "no relevance signal reached the floor", 0.0)
        return _Pre(cid, tid, symbols, 0.0, (why,), False, False)
    score = 1.0 - miss
    nt = _name_terms(doc.name)
    test_error = _test_error_class(doc, nt)
    if facets.error_class and not test_error:
        f = cfg.behavior_mismatch_factor
        score *= f
        reasons.append(
            RelevanceReason(
                R_BEHAVIOR, "criterion is about an error, test checks none", f
            )
        )
    elif not facets.error_class and not facets.constraint and test_error:
        f = cfg.success_mismatch_factor
        score *= f
        reasons.append(
            RelevanceReason(
                R_BEHAVIOR,
                "test checks an error, criterion is about normal behaviour",
                f,
            )
        )
    typed = [a.exception_type.casefold() for a in doc.assertions if a.exception_type]
    specific = [
        t for t in typed if t.rsplit(".", 1)[-1] not in ("exception", "baseexception")
    ]
    if facets.exceptions and specific:
        if not any(_exc_match(e, t) for e in facets.exceptions for t in specific):
            f = cfg.exception_type_factor
            score *= f
            detail = f"test expects {','.join(sorted(set(specific)))}, criterion names {','.join(facets.exceptions)}"
            reasons.append(RelevanceReason(R_EXC_TYPE, detail, f))
    names = {
        n.rsplit(".", 1)[-1].casefold()
        for a in doc.assertions
        for n in a.symbol_names
        if n
    }
    if names and symbols:
        wanted = _symbol_last_names(symbols)
        subject_text = "\n".join(a.subject for a in doc.assertions).casefold()
        if not (names & wanted) and not any(w in subject_text for w in wanted):
            f = cfg.other_symbols_factor
            score *= f
            detail = f"assertions concern {','.join(sorted(names))}, not {','.join(sorted(wanted))}"
            reasons.append(RelevanceReason(R_OTHER_SYMBOLS, detail, f))
    return _Pre(cid, tid, symbols, score, tuple(reasons), False, True)


def score_relevance(
    criteria: Sequence[CriterionInput],
    test_docs: Sequence[TestDoc],
    connections: Mapping[tuple[str, str], Sequence[str]],
    config: RelevanceConfig | None = None,
) -> RelevanceSet:
    """Score every connected ``(criterion, test)`` pair, plus hinted pairs.

    ``connections`` is ``connected_pairs(...)``: the pairs reachable through a changed
    symbol. Pairs neither connected nor hinted are not scored (no edge). The BM25
    corpus is ``test_docs`` (pin it: ``idf`` depends on it). Unknown ids are ignored.
    Deterministic and independent of input order.
    """

    cfg = config or RelevanceConfig()
    docs = {d.test_id: d for d in sorted(test_docs, key=lambda d: d.test_id)}
    crits = {c.criterion_id: c for c in sorted(criteria, key=lambda c: c.criterion_id)}
    index = BM25Index(
        {tid: _bm25_tokens(d) for tid, d in docs.items()}, k1=cfg.bm25_k1, b=cfg.bm25_b
    )
    pairs: dict[tuple[str, str], tuple[str, ...]] = {
        k: tuple(sorted(v))
        for k, v in connections.items()
        if k[0] in crits and k[1] in docs
    }
    for cid, crit in crits.items():
        for tid in docs:
            if (cid, tid) not in pairs and any(
                hint_matches(h, tid) for h in crit.tests
            ):
                pairs[(cid, tid)] = ()
    pre = [
        _score_pair(crits[cid], docs[tid], syms, index, cfg)
        for (cid, tid), syms in sorted(pairs.items())
    ]
    strong: Counter[str] = Counter(
        p.test_id
        for p in pre
        if not p.hinted and p.r0 >= cfg.specificity_count_threshold
    )
    items: list[CriterionTestRelevance] = []
    for p in pre:
        r, reasons = p.r0, list(p.reasons)
        if p.fired and not p.hinted:
            if p.r0 >= cfg.specificity_count_threshold:
                f = specificity_factor(strong[p.test_id], cfg)
                if f < 1.0:
                    r *= f
                    detail = f"test strongly related to {strong[p.test_id]} criteria"
                    reasons.append(RelevanceReason(R_SPECIFICITY, detail, f))
            if r < cfg.r_floor:
                r = 0.0
                reasons.append(
                    RelevanceReason(R_BELOW_FLOOR, f"under r_floor {cfg.r_floor}", 0.0)
                )
        items.append(
            CriterionTestRelevance(
                p.criterion_id, p.test_id, r, tuple(reasons), p.symbols
            )
        )
    return RelevanceSet(
        _rank(items), {**cfg.to_dict(), "algo_version": RELEVANCE_ALGO_VERSION}
    )


def _rank(
    items: Sequence[CriterionTestRelevance],
) -> tuple[CriterionTestRelevance, ...]:
    """Deterministic order: criterion id, ``r_ct`` desc, test id; 1-based rank per criterion."""

    out: list[CriterionTestRelevance] = []
    prev: str | None = None
    rank = 0
    for it in sorted(items, key=lambda i: (i.criterion_id, -i.r_ct, i.test_id)):
        rank = rank + 1 if it.criterion_id == prev else 1
        prev = it.criterion_id
        out.append(
            CriterionTestRelevance(
                it.criterion_id, it.test_id, it.r_ct, it.reasons, it.symbol_ids, rank
            )
        )
    return tuple(out)


def relevance_from_links(
    criteria: Sequence[CriterionInput],
    test_docs: Sequence[TestDoc],
    c2s_links: Iterable[Link],
    s2t_edges: Iterable[SymbolTestEdge],
    config: RelevanceConfig | None = None,
) -> RelevanceSet:
    """Convenience: ``connected_pairs`` followed by ``score_relevance``."""

    return score_relevance(
        criteria, test_docs, connected_pairs(c2s_links, s2t_edges), config
    )


def relevant_tests(
    rel: RelevanceSet, criterion_id: str, threshold: float = 0.3
) -> list[str]:
    """Test ids with ``r_ct >= threshold`` for a criterion, best first."""

    return [i.test_id for i in rel.for_criterion(criterion_id) if i.r_ct >= threshold]
