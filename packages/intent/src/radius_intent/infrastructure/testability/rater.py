"""Deterministic, rule-based testability rater (IN-05).

Pure function of ``(criterion text, hints, source kind, word lists)``: no LLM,
network, clock or randomness. Every rule has a stable id; the result lists the
fired rules with their matched spans in a fixed order.

Scoring. Each fired rule adds its weight to one group (behavioral,
structural, non_functional, vague, external). The decision then follows a
fixed precedence, see :meth:`DeterministicTestabilityRater._decide`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from radius_intent.domain import (
    Criterion,
    IntentSourceKind,
    Testability,
    TestabilityAssessment,
)
from radius_intent.infrastructure.testability.lexicon import (
    WordLists,
    load_wordlists,
)
from radius_intent.infrastructure.testability.result import (
    Confidence,
    Group,
    MatchSpan,
    Reason,
    TestabilityResult,
)

#: Only this many leading characters are analysed (bounds time on huge input).
MAX_ANALYSED_CHARS = 4000
#: At most this many spans are reported per rule.
MAX_SPANS_PER_RULE = 5
_SNIPPET_CHARS = 40


@dataclass(frozen=True)
class RuleSpec:
    """Static description of one rule."""

    rule_id: str
    group: Group
    weight: int
    phrase: str


def _spec(rule_id: str, group: Group, weight: int, phrase: str) -> RuleSpec:
    return RuleSpec(rule_id, group, weight, phrase)


#: The complete rule set of ``testability-rules-v1``.
RULES: dict[str, RuleSpec] = {
    spec.rule_id: spec
    for spec in (
        _spec("gherkin_scenario", Group.BEHAVIORAL, 3, "Gherkin scenario"),
        _spec("explicit_test_hint", Group.BEHAVIORAL, 3, "explicit test in intent.yml"),
        _spec("path_hint", Group.BEHAVIORAL, 1, "code path hint in intent.yml"),
        _spec("spec_file_origin", Group.BEHAVIORAL, 1, "authored in the spec file"),
        _spec("http_status", Group.BEHAVIORAL, 3, "HTTP status"),
        _spec("observable_verb", Group.BEHAVIORAL, 2, "observable action"),
        _spec("error_wording", Group.BEHAVIORAL, 2, "error wording"),
        _spec("quantity_threshold", Group.BEHAVIORAL, 2, "quantity"),
        _spec("code_reference", Group.BEHAVIORAL, 2, "code or file reference"),
        _spec("condition_clause", Group.BEHAVIORAL, 1, "condition"),
        _spec("result_clause", Group.BEHAVIORAL, 1, "result clause"),
        _spec("modal_verb", Group.BEHAVIORAL, 1, "modal verb"),
        _spec("passive_requirement", Group.BEHAVIORAL, 1, "required outcome"),
        _spec("comparator", Group.BEHAVIORAL, 1, "comparator"),
        _spec("negation", Group.BEHAVIORAL, 1, "negation"),
        _spec("literal_value", Group.BEHAVIORAL, 1, "quoted literal"),
        _spec("structural_verb", Group.STRUCTURAL, 3, "structural change"),
        _spec("version_number", Group.STRUCTURAL, 2, "version number"),
        _spec("structural_noun", Group.STRUCTURAL, 1, "structural target"),
        _spec("docs_config_edit", Group.STRUCTURAL, 3, "edit of docs or config"),
        _spec("nfr_term", Group.NON_FUNCTIONAL, 3, "non-functional quality"),
        _spec("time_budget", Group.NON_FUNCTIONAL, 3, "time or size budget"),
        _spec("measure_tool", Group.NON_FUNCTIONAL, 3, "named tool or standard"),
        _spec("placeholder", Group.VAGUE, 4, "placeholder"),
        _spec("vague_adjective", Group.VAGUE, 3, "subjective wording"),
        _spec("weasel_word", Group.VAGUE, 2, "hedge"),
        _spec("too_short", Group.VAGUE, 2, "very short statement"),
        _spec("external_judgment", Group.EXTERNAL, 3, "human or legal judgment"),
        _spec("live_system", Group.EXTERNAL, 3, "live external system"),
        _spec("non_english_fallback", Group.META, 0, "language not recognised"),
        _spec("text_truncated", Group.META, 0, "text truncated"),
        _spec("no_testable_signal", Group.META, 0, "no testable signal"),
        _spec("nfr_without_threshold", Group.META, 0, "no threshold or tool"),
    )
}

_TIME_SIZE_UNITS = (
    r"(?:ms|milliseconds?|s|secs?|seconds?|min|mins|minutes?|"
    r"kb|mb|gb|kib|mib|gib|bytes?)"
)
_TIME_BUDGET = re.compile(
    r"(?<![\w])(?:within|under|below|less than|fewer than|at most|no more than"
    r"|up to|in under|<=?|\u2264)\s*\d+(?:[.,]\d+)?\s?"
    + _TIME_SIZE_UNITS
    + r"(?![\w])",
    re.IGNORECASE,
)
_HTTP_STATUS = re.compile(
    r"(?<![\w.])(?:http\s*)?(?:status(?:\s+code)?|code|returns?|responds?"
    r"(?:\s+with)?|response|http|error)\s*:?\s*([1-5]\d\d)(?![\w%.])"
    r"|(?<![\w.])[1-5]\d\d\s+(?:error|response|status|ok|created|not found"
    r"|unauthorized|forbidden|bad request|conflict)(?![\w])",
    re.IGNORECASE,
)
_VERSION = re.compile(r"(?<![\w.])v?\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?(?![\w])")
_LITERAL = re.compile(r"[\"\u201c][^\"\u201d\n]{1,60}[\"\u201d]")
_PASSIVE = re.compile(
    r"(?<![\w])(?:must|shall|should|will|needs? to|has to|have to)\s+"
    r"(?:not\s+)?be\s+\w+(?:ed|en)(?![\w])",
    re.IGNORECASE,
)
_RATE = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s?(?:[a-z]+\s)?(?:per|/)\s?"
    r"(?:second|sec|s|minute|min|hour|day)(?![\w])",
    re.IGNORECASE,
)
_BARE_STATUS = re.compile(r"(?<![\w.])[1-5]\d\d(?![\w%.])")
_EDIT_VERBS = (
    r"add|update|write|edit|fix|correct|create|include|extend|remove|delete|drop"
    r"|rename|move|replace|document|regenerate|refresh"
)
_GHERKIN_START = re.compile(r"\s*scenario(?: outline)?\s*:", re.IGNORECASE)
_GHERKIN_STEP = re.compile(r"(?<![\w])(?:given|when|then)(?![\w])", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+")

_BACKTICK = r"`[^`\n]{1,80}`"
_LEADING_SLASH_PATH = r"(?<![\w./-])(?:\.{1,2}/|/)[\w.{}:-]+(?:/[\w.{}:-]+)*"
_DIR_FILE = r"(?<![\w./-])[\w-]+(?:/[\w.-]+)+\.\w+"
_SNAKE = r"(?<![\w])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w])"
_CAMEL = r"(?<![\w])[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+(?![\w])"
_CALL = r"(?<![\w])[A-Za-z_][\w.]*\(\)"


def phrase_regex(words: tuple[str, ...]) -> re.Pattern[str]:
    """Compile a whole-word, case-insensitive alternation (longest first)."""
    ordered = sorted(set(words), key=lambda w: (-len(w), w))
    body = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in ordered)
    return re.compile(rf"(?<![\w'])(?:{body})(?![\w])", re.IGNORECASE)


def _clip(text: str) -> str:
    """Make a matched snippet safe to quote: printable, short, one line."""
    flat = "".join(ch if ch.isprintable() else " " for ch in text)
    flat = " ".join(flat.split())
    return flat if len(flat) <= _SNIPPET_CHARS else flat[: _SNIPPET_CHARS - 1] + "~"


Matcher = Callable[[str], list[tuple[int, int]]]


def _finder(*patterns: re.Pattern[str]) -> Matcher:
    def find(text: str) -> list[tuple[int, int]]:
        spans = [m.span() for p in patterns for m in p.finditer(text)]
        return sorted(spans)

    return find


@dataclass(frozen=True)
class _Features:
    """Everything the decision needs, derived from one text."""

    reasons: dict[str, Reason]
    scores: dict[Group, int]
    distinct: dict[str, tuple[str, ...]]

    def fired(self, rule_id: str) -> bool:
        return rule_id in self.reasons

    def score(self, group: Group) -> int:
        return self.scores.get(group, 0)


class DeterministicTestabilityRater:
    """Rule-based :class:`~radius_intent.interfaces.TestabilityRater`.

    ``rate`` implements the port; ``explain`` returns the full result with
    confidence, ordered reasons and rewrite hints.
    """

    def __init__(self, wordlists: WordLists | None = None) -> None:
        words = wordlists if wordlists is not None else load_wordlists()
        self._words = words
        self._lists: dict[str, re.Pattern[str]] = {
            name: phrase_regex(words.get(name))
            for name in (
                "modal_verbs",
                "observable_verbs",
                "error_words",
                "comparators",
                "negations",
                "condition_words",
                "result_words",
                "structural_verbs",
                "structural_nouns",
                "non_functional_terms",
                "measure_tools",
                "vague_adjectives",
                "weasel_words",
                "placeholders",
                "external_judgment",
                "live_system_terms",
            )
        }
        units = "|".join(
            re.escape(u)
            for u in sorted(words.get("quantity_units"), key=lambda u: -len(u))
        )
        self._quantity = re.compile(
            rf"(?<![\w.])\d+(?:[.,]\d+)?\s?(?:{units})(?![\w])", re.IGNORECASE
        )
        nouns = "|".join(
            re.escape(n).replace(r"\ ", r"\s+")
            for n in sorted(words.get("structural_nouns"), key=lambda n: (-len(n), n))
        )
        self._docs_edit = re.compile(
            rf"\s*(?:{_EDIT_VERBS})(?![\w])[^.\n]{{0,80}}?(?<![\w'])(?:{nouns})(?![\w])",
            re.IGNORECASE,
        )
        exts = "|".join(re.escape(e) for e in words.get("file_extensions"))
        filename = rf"(?<![\w./-])[\w-]+(?:\.[\w-]+)*\.(?:{exts})(?![\w])"
        self._code_ref = re.compile(
            "|".join(
                (
                    _BACKTICK,
                    _LEADING_SLASH_PATH,
                    _DIR_FILE,
                    filename,
                    _SNAKE,
                    _CAMEL,
                    _CALL,
                )
            )
        )
        self._non_english = phrase_regex(words.get("non_english_markers"))
        self._matchers: tuple[tuple[str, Matcher], ...] = (
            ("http_status", self._status_codes),
            ("observable_verb", _finder(self._lists["observable_verbs"])),
            ("error_wording", _finder(self._lists["error_words"])),
            ("quantity_threshold", _finder(self._quantity, _RATE)),
            ("code_reference", _finder(self._code_ref)),
            ("condition_clause", _finder(self._lists["condition_words"])),
            ("result_clause", _finder(self._lists["result_words"])),
            ("modal_verb", _finder(self._lists["modal_verbs"])),
            ("passive_requirement", _finder(_PASSIVE)),
            ("comparator", _finder(self._lists["comparators"])),
            ("negation", _finder(self._lists["negations"])),
            ("literal_value", _finder(_LITERAL)),
            ("structural_verb", _finder(self._lists["structural_verbs"])),
            ("structural_noun", _finder(self._lists["structural_nouns"])),
            ("docs_config_edit", self._leading_edit),
            ("nfr_term", _finder(self._lists["non_functional_terms"])),
            ("time_budget", _finder(_TIME_BUDGET)),
            ("measure_tool", _finder(self._lists["measure_tools"])),
            ("placeholder", _finder(self._lists["placeholders"])),
            ("vague_adjective", _finder(self._lists["vague_adjectives"])),
            ("weasel_word", _finder(self._lists["weasel_words"])),
            ("external_judgment", _finder(self._lists["external_judgment"])),
            ("live_system", _finder(self._lists["live_system_terms"])),
        )

    def _status_codes(self, scan: str) -> list[tuple[int, int]]:
        """Contextual HTTP status codes that are not quantities ("404 users")."""
        out = []
        for m in _HTTP_STATUS.finditer(scan):
            digits = re.search(r"[1-5]\d\d", m.group(0))
            start = m.start() + (digits.start() if digits else 0)
            if self._quantity.match(scan, start) is None:
                out.append(m.span())
        return out

    def _leading_edit(self, scan: str) -> list[tuple[int, int]]:
        m = self._docs_edit.match(scan)
        return [m.span()] if m else []

    # -- port -------------------------------------------------------------

    def rate(self, criterion: Criterion) -> TestabilityAssessment:
        """Implement the ``TestabilityRater`` port."""
        return self.explain(criterion).to_assessment()

    def explain(self, criterion: Criterion) -> TestabilityResult:
        """Rate ``criterion`` using its text, hints and source kind."""
        return self.rate_text(
            criterion.text,
            tests=criterion.hints.tests,
            paths=criterion.hints.paths,
            source_kind=criterion.origin.source.kind,
        )

    # -- text level -------------------------------------------------------

    def rate_text(
        self,
        text: str,
        *,
        tests: tuple[str, ...] = (),
        paths: tuple[str, ...] = (),
        source_kind: IntentSourceKind | None = None,
    ) -> TestabilityResult:
        """Rate raw criterion text. Never raises for any ``str`` input."""
        truncated = len(text) > MAX_ANALYSED_CHARS
        scan = text[:MAX_ANALYSED_CHARS].replace("\u2019", "'")
        feats = self._features(scan, tests, paths, source_kind, truncated)
        return self._decide(scan, feats, truncated, bool(tests))

    # -- feature extraction -----------------------------------------------

    def _features(
        self,
        scan: str,
        tests: tuple[str, ...],
        paths: tuple[str, ...],
        source_kind: IntentSourceKind | None,
        truncated: bool,
    ) -> _Features:
        reasons: dict[str, Reason] = {}
        distinct: dict[str, tuple[str, ...]] = {}

        def add(rule_id: str, spans: list[tuple[int, int]], weight: int | None = None):
            spec = RULES[rule_id]
            shown = tuple(
                MatchSpan(a, b, _clip(scan[a:b])) for a, b in spans[:MAX_SPANS_PER_RULE]
            )
            quote = ", ".join(repr(s.text) for s in shown[:3])
            detail = f"{spec.phrase}: {quote}" if quote else spec.phrase
            reasons[rule_id] = Reason(
                rule_id,
                spec.group,
                spec.weight if weight is None else weight,
                shown,
                detail,
            )

        if _GHERKIN_START.match(scan):
            add("gherkin_scenario", [(0, scan.index(":") + 1)])
        if tests:
            add("explicit_test_hint", [])
        if paths:
            add("path_hint", [])
        if source_kind is IntentSourceKind.SPEC_FILE:
            add("spec_file_origin", [])

        for rule_id, find in self._matchers:
            spans = find(scan)
            if not spans:
                continue
            if rule_id in ("vague_adjective", "weasel_word"):
                words = tuple(sorted({scan[a:b].casefold() for a, b in spans}))
                distinct[rule_id] = words
                add(rule_id, spans, RULES[rule_id].weight * min(len(words), 2))
            else:
                add(rule_id, spans)

        if "docs_config_edit" in reasons and "condition_clause" in reasons:
            del reasons["docs_config_edit"]
        if "non_english_fallback" not in reasons and self._looks_non_english(scan):
            add("non_english_fallback", [])
            if "http_status" not in reasons:
                spans = self._bare_status(scan)
                if spans:
                    add("http_status", spans)
        if "version_number" not in reasons and "structural_verb" in reasons:
            spans = _finder(_VERSION)(scan)
            if spans:
                add("version_number", spans)
        if len(_WORD.findall(scan)) < 3 and "placeholder" not in reasons:
            add("too_short", [])
        if truncated:
            add("text_truncated", [])

        scores: dict[Group, int] = {}
        for reason in reasons.values():
            scores[reason.group] = scores.get(reason.group, 0) + reason.weight
        return _Features(reasons, scores, distinct)

    def _bare_status(self, scan: str) -> list[tuple[int, int]]:
        """Language-neutral status codes: a 3-digit code not followed by a unit."""
        out = []
        for m in _BARE_STATUS.finditer(scan):
            if self._quantity.match(scan, m.start()) is None:
                out.append(m.span())
        return out

    def _looks_non_english(self, scan: str) -> bool:
        letters = [ch for ch in scan if ch.isalpha()]
        if not letters:
            return False
        ascii_share = sum(1 for ch in letters if ch.isascii()) / len(letters)
        if ascii_share < 0.7:
            return True
        words = _WORD.findall(scan)
        markers = len(self._non_english.findall(scan))
        return markers >= 2 and markers / max(len(words), 1) >= 0.15

    # -- decision ---------------------------------------------------------

    def _decide(
        self, scan: str, f: _Features, truncated: bool, has_tests: bool
    ) -> TestabilityResult:
        b = f.score(Group.BEHAVIORAL)
        s = f.score(Group.STRUCTURAL)
        n = f.score(Group.NON_FUNCTIONAL)
        v = f.score(Group.VAGUE)
        x = f.score(Group.EXTERNAL)
        explicit = f.fired("http_status") or f.fired("gherkin_scenario") or has_tests
        measurable = (
            f.fired("quantity_threshold")
            or f.fired("time_budget")
            or f.fired("measure_tool")
        )
        frame = f.fired("gherkin_scenario") or (
            f.fired("condition_clause") and f.fired("result_clause")
        )
        extra: list[str] = []

        if f.fired("placeholder") and not explicit:
            rating, conf = Testability.SUBJECTIVE_OR_VAGUE, Confidence.HIGH
        elif x >= 3 and x + 1 >= b and not has_tests:
            rating = Testability.UNTESTABLE_EXTERNAL
            conf = Confidence.HIGH if x >= 6 else Confidence.MEDIUM
        elif n >= 3 and not explicit:
            if measurable:
                rating = Testability.NON_FUNCTIONAL_MEASURABLE
                conf = Confidence.HIGH if (n >= 5 and v == 0) else Confidence.MEDIUM
            elif b >= 4 and b > v:
                rating, conf = Testability.BEHAVIORAL_TESTABLE, Confidence.LOW
            else:
                rating = Testability.SUBJECTIVE_OR_VAGUE
                conf = Confidence.MEDIUM
                extra.append("nfr_without_threshold")
        elif s >= 3 and s >= b and s - v >= 2 and not frame:
            rating = Testability.STRUCTURAL_CHECKABLE
            conf = Confidence.HIGH if (s >= 5 and s - v >= 3) else Confidence.MEDIUM
        elif b >= 2 and b > v:
            rating = Testability.BEHAVIORAL_TESTABLE
            margin = b - max(v, s, x)
            if b >= 6 and margin >= 3:
                conf = Confidence.HIGH
            elif b >= 3 and margin >= 2:
                conf = Confidence.MEDIUM
            else:
                conf = Confidence.LOW
        else:
            rating = Testability.SUBJECTIVE_OR_VAGUE
            if v >= 4 and b <= 2:
                conf = Confidence.HIGH
            elif v >= 2:
                conf = Confidence.MEDIUM
            else:
                conf = Confidence.LOW
                if v == 0:
                    extra.append("no_testable_signal")

        if f.fired("non_english_fallback"):
            conf = Confidence.LOW
        elif truncated and conf is Confidence.HIGH:
            conf = Confidence.MEDIUM

        reasons = dict(f.reasons)
        for rule_id in extra:
            spec = RULES[rule_id]
            reasons[rule_id] = Reason(rule_id, spec.group, 0, (), spec.phrase)
        ordered = self._order(reasons, rating)
        hints = self._rewrite_hints(rating, reasons, f)
        scores = (
            ("behavioral", b),
            ("structural", s),
            ("non_functional", n),
            ("vague", v),
            ("external", x),
        )
        return TestabilityResult(
            rating=rating,
            confidence=conf,
            reasons=ordered,
            summary=_summary(rating, ordered),
            rewrite_hints=hints,
            scores=scores,
        )

    @staticmethod
    def _order(reasons: dict[str, Reason], rating: Testability) -> tuple[Reason, ...]:
        supporting = {
            Testability.BEHAVIORAL_TESTABLE: Group.BEHAVIORAL,
            Testability.STRUCTURAL_CHECKABLE: Group.STRUCTURAL,
            Testability.NON_FUNCTIONAL_MEASURABLE: Group.NON_FUNCTIONAL,
            Testability.UNTESTABLE_EXTERNAL: Group.EXTERNAL,
            Testability.SUBJECTIVE_OR_VAGUE: Group.VAGUE,
        }[rating]

        def key(r: Reason) -> tuple[int, int, int, str]:
            first = r.spans[0].start if r.spans else -1
            return (0 if r.group is supporting else 1, -r.weight, first, r.rule_id)

        return tuple(sorted(reasons.values(), key=key))

    @staticmethod
    def _rewrite_hints(
        rating: Testability, reasons: dict[str, Reason], f: _Features
    ) -> tuple[str, ...]:
        if rating in (
            Testability.BEHAVIORAL_TESTABLE,
            Testability.STRUCTURAL_CHECKABLE,
            Testability.NON_FUNCTIONAL_MEASURABLE,
        ):
            return ()
        hints: list[str] = []
        if "placeholder" in reasons:
            hints.append("Replace the placeholder with the concrete criterion.")
        if "nfr_without_threshold" in reasons:
            hints.append(
                "Add a measurable threshold (for example 'p95 latency under 200 ms') "
                "or name the tool and standard that checks it."
            )
        if "vague_adjective" in f.distinct:
            words = ", ".join(f.distinct["vague_adjective"][:3])
            hints.append(
                f"Replace subjective wording ({words}) with an observable outcome "
                "or a measure (for example 'returns X when Y', 'fewer than N lines')."
            )
        if "weasel_word" in f.distinct:
            words = ", ".join(f.distinct["weasel_word"][:3])
            hints.append(f"Remove hedges ({words}); list the exact cases instead.")
        if "too_short" in reasons:
            hints.append(
                "Say who does what and what should be observable "
                "(condition and expected result)."
            )
        if "no_testable_signal" in reasons:
            hints.append(
                "State the observable behavior: the input or condition and the "
                "expected output."
            )
        if rating is Testability.UNTESTABLE_EXTERNAL:
            hints.append(
                "Link the approval or ticket, or name an automatable proxy check."
            )
        if "non_english_fallback" in reasons:
            hints.append(
                "Add an English summary or an explicit test in .radius/intent.yml "
                "so Radius can rate it."
            )
        return tuple(dict.fromkeys(hints))


_LABELS: dict[Testability, str] = {
    Testability.BEHAVIORAL_TESTABLE: "Describes observable behavior",
    Testability.STRUCTURAL_CHECKABLE: "Structural change, checkable by diff or static analysis",
    Testability.NON_FUNCTIONAL_MEASURABLE: "Non-functional with a measure",
    Testability.SUBJECTIVE_OR_VAGUE: "Too vague to verify mechanically",
    Testability.UNTESTABLE_EXTERNAL: (
        "Needs human, product or legal judgment or a live external system"
    ),
}


def _summary(rating: Testability, ordered: tuple[Reason, ...]) -> str:
    shown = [r.detail for r in ordered[:3] if r.group is not Group.META or r.spans]
    label = _LABELS[rating]
    if not shown:
        return f"{label}: no testable cue found."
    return f"{label} ({'; '.join(shown)})."
