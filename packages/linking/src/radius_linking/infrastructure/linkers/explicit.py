"""Explicit-hint linker: author path/test hints and file paths named in the criterion.

Sources, strongest first: ``path::symbol`` hints (0.95), exact file hints (0.85),
file paths written in the criterion text (0.9), wildcard hints (0.7), directory
or ``**`` hints (0.5), and ``tests`` hints matched to a symbol through the usual
test-naming conventions (up to 0.8). Hints are advisory author input, so even an
explicit link stays below 1.0 and is capped again by the combiner.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath

from radius_linking.domain import (
    LINKER_EXPLICIT,
    CriterionInput,
    Link,
    LinkContext,
    Reason,
    SymbolDoc,
)
from radius_linking.domain.text import name_terms
from radius_linking.infrastructure.linkers.common import (
    glob_match,
    normalize_path,
    pattern_specificity,
    reason,
    sort_reasons,
)

VERSION = "explicit-v1"
_PATH_MENTION = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|java|kt|rb|rs|cs|php|swift|scala))\b"
)
SYMBOL_HINT = 0.95
MENTION = 0.9
_TEST_PREFIX = re.compile(r"^(test_|tests_)|(_test|_tests|\.test|\.spec)$")


def _stem_of(path: str) -> str:
    stem = PurePosixPath(path).stem
    stem = re.sub(r"\.(test|spec)$", "", stem)
    return _TEST_PREFIX.sub("", stem)


def _symbol_matches(sym: SymbolDoc, wanted: str) -> bool:
    w = wanted.strip()
    q = sym.qualified_name
    return bool(w) and (q == w or sym.simple_name == w or q.startswith(w + "."))


def _test_hint_score(sym: SymbolDoc, test_ref: str) -> tuple[float, str]:
    """Score a ``tests/test_x.py::test_name`` hint against a symbol (0 when unrelated)."""

    path, _, name = test_ref.partition("::")
    file_match = _stem_of(path) == PurePosixPath(sym.path).stem and bool(_stem_of(path))
    sym_terms = set(name_terms(sym.simple_name))
    test_terms = {t for t in name_terms(name) if t not in {"test", "tests"}}
    name_match = bool(sym_terms) and sym_terms <= test_terms
    if not (file_match or name_match):
        return 0.0, ""
    score = 0.35 * file_match + 0.45 * name_match
    return score, f"test hint {test_ref} (file={file_match}, name={name_match})"


def match_hints(
    criterion: CriterionInput, symbols: Sequence[SymbolDoc]
) -> dict[str, list[Reason]]:
    """Explicit evidence per ``symbol_id`` (shared with the structural linker)."""

    out: dict[str, list[Reason]] = {}

    def add(sym: SymbolDoc, kind: str, detail: str, score: float) -> None:
        out.setdefault(sym.symbol_id, []).append(
            reason(LINKER_EXPLICIT, kind, detail, score)
        )

    for hint in criterion.paths:
        glob_part, sep, sym_part = hint.partition("::")
        glob_part = glob_part.strip()
        if not glob_part:
            continue
        for sym in symbols:
            if not glob_match(glob_part, sym.path):
                continue
            if sep:
                if _symbol_matches(sym, sym_part):
                    add(sym, "path_symbol_hint", f"hint {hint}", SYMBOL_HINT)
            else:
                add(sym, "path_hint", f"hint {hint}", pattern_specificity(glob_part))
    for test_ref in criterion.tests:
        for sym in symbols:
            score, detail = _test_hint_score(sym, test_ref)
            if score > 0:
                add(sym, "test_hint", detail, min(0.8, score))
    mentions = {normalize_path(m) for m in _PATH_MENTION.findall(criterion.full_text)}
    for mention in sorted(mentions):
        for sym in symbols:
            if sym.path == mention or sym.path.endswith("/" + mention):
                add(sym, "path_mention", f"criterion mentions {mention}", MENTION)
    return out


class ExplicitLinker:
    name = LINKER_EXPLICIT
    version = VERSION

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]:
        links: list[Link] = []
        for crit in criteria:
            for symbol_id, reasons in match_hints(crit, symbols).items():
                score = max(r.score for r in reasons)
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


__all__ = ["VERSION", "ExplicitLinker", "match_hints"]
