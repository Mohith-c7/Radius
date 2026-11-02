# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Fuzz-style, determinism, performance and ReDoS-guard tests."""

from __future__ import annotations

import ast
import random
import re
import time
from pathlib import Path

import pytest
import radius_intent.infrastructure.extraction as extraction_pkg
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from extraction_helpers import FIXTURES, src
from radius_intent.domain import IntentSourceKind
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    ExtractionConfig,
)
from radius_intent.infrastructure.extraction.config import (
    DEFAULT_EXCLUDED_PATTERN,
    DEFAULT_SECTION_PATTERN,
    DEFAULT_TABLE_COLUMN_PATTERN,
)

EXTRACTOR = DeterministicCriterionExtractor()
# Generous wall-clock bounds: real runs take well under a third of these.
BOUND_SECONDS = 15.0


def timed(text: str, kind: IntentSourceKind = IntentSourceKind.PR_BODY):
    source = src(text, kind)
    start = time.perf_counter()
    report = EXTRACTOR.extract_report(source)
    return report, time.perf_counter() - start


AC = "## Acceptance Criteria\n"
PATHOLOGICAL = {
    "deeply_nested_lists": "".join(
        "  " * (i % 200) + f"- item {i}\n" for i in range(3000)
    ),
    "nesting_beyond_depth_cap": "".join(" " * i + "- x\n" for i in range(300)),
    "nested_blockquotes": ">" * 5000 + " must do\n",
    "very_long_single_line_1mb": "a" * 1_000_000,
    "very_long_modal_line": "must " * 100_000,
    "unmatched_fences": "```\n" * 50_000,
    "unmatched_fence_with_lists": AC + "```\n- [ ] a\n" * 1000,
    "backtick_wall": "`" * 1_000_000,
    "tilde_wall": "~" * 100_000 + "\n",
    "emphasis_wall": "**" * 100_000 + "\n" + "__" * 100_000,
    "pipe_wall": "|" * 200_000 + "\n" + "|-" * 100 + "\n",
    "table_without_end": "| Criterion |\n|---|\n" + "| Row number here |\n" * 20_000,
    "comment_storm": "<!-- x -->" * 50_000,
    "unterminated_comment_storm": "<!--" * 50_000,
    "heading_wall": "#" * 100_000 + " title\n",
    "many_headings": "".join(
        f"## h{i}\n- [ ] item {i} must work\n" for i in range(5000)
    ),
    "gherkin_flood": "Scenario: s\nGiven a\nWhen b\nThen c\n" * 5000,
    "sentence_flood": "The a must b. " * 50_000,
    "checkbox_flood": "- [ ] " * 100_000,
    "colon_flood": "Acceptance criteria:\n" * 20_000,
    "mixed_control_chars": "\x00\x0b\x0c\x1f  ﻿​" * 20_000,
    "lone_cr_lines": "- [ ] a\r" * 50_000,
}


@pytest.mark.parametrize("name", sorted(PATHOLOGICAL))
def test_pathological_inputs_terminate_quickly_without_crashing(name):
    report, elapsed = timed(PATHOLOGICAL[name])
    assert elapsed < BOUND_SECONDS, f"{name} took {elapsed:.1f}s"
    assert len(report.criteria) <= ExtractionConfig().max_criteria_per_source
    assert len(report.diagnostics) <= 1001


def test_one_megabyte_realistic_body_under_bound_and_capped():
    body = AC + "".join(
        f"- Users can do thing number {i} with data\n" for i in range(25_000)
    )
    assert len(body) > 1_000_000
    report, elapsed = timed(body)
    assert elapsed < BOUND_SECONDS
    codes = {d.code for d in report.diagnostics}
    assert "max_criteria" in codes
    assert len(report.criteria) <= ExtractionConfig().max_criteria_per_source


def test_list_depth_cap_is_reported_and_bounded():
    report, _ = timed(AC + "".join(" " * i + f"- level {i}\n" for i in range(200)))
    assert "max_list_depth" in {d.code for d in report.diagnostics}
    assert max(t.depth for t in report.traces) <= ExtractionConfig().max_list_depth


def _scaling_run(builder, n: int) -> float:
    text = builder(n)
    best = float("inf")
    for _ in range(3):
        best = min(best, timed(text)[1])
    return best


@pytest.mark.parametrize(
    "builder",
    [
        lambda n: AC + "".join(f"- criterion {i} holds\n" for i in range(n)),
        lambda n: "The a must b. " * n,
        lambda n: "\n".join("> quote" for _ in range(n)),
        lambda n: "".join("  " * (i % 50) + f"- n{i}\n" for i in range(n)),
        lambda n: "| Criterion |\n|---|\n" + "| Row here |\n" * n,
    ],
    ids=["list", "sentences", "quotes", "nesting", "table"],
)
def test_runtime_scales_roughly_linearly(builder):
    small = _scaling_run(builder, 4_000)
    large = _scaling_run(builder, 32_000)  # 8x the input
    # Quadratic behaviour would give ~64x; allow generous noise on shared CI.
    assert large < max(small * 30, 0.5), (small, large)


REDOS_PROBES = [
    "a" * 50_000 + "!",
    "- " * 50_000,
    "1." * 50_000,
    "[ ]" * 50_000,
    "(" * 50_000 + "x",
    "*" * 50_000 + "x*",
    "x " * 50_000 + "\n" + "-" * 50_000,
    "| " * 50_000 + "\n" + "|:-:" * 20_000,
    "Given " * 20_000 + "\nWhen " * 20_000,
    ("ab" * 30_000) + ". " + ("A" * 30_000),
]


@pytest.mark.parametrize("probe", range(len(REDOS_PROBES)))
def test_redos_probes_finish_quickly(probe):
    _, elapsed = timed(REDOS_PROBES[probe])
    assert elapsed < BOUND_SECONDS


NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)[+*{]")


def _regex_literals() -> list[tuple[str, str]]:
    """Collect string literals passed to ``re.compile`` in the extraction package."""
    found: list[tuple[str, str]] = []
    pkg_dir = Path(extraction_pkg.__file__).parent
    for path in sorted(pkg_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compile"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append((path.name, node.args[0].value))
    return found


def test_regex_literals_have_no_nested_quantifiers():
    literals = _regex_literals()
    assert literals, "expected to find compiled patterns"
    bad = [(f, p) for f, p in literals if NESTED_QUANTIFIER.search(p)]
    assert not bad, bad


@pytest.mark.parametrize(
    "pattern",
    [DEFAULT_SECTION_PATTERN, DEFAULT_EXCLUDED_PATTERN, DEFAULT_TABLE_COLUMN_PATTERN],
)
def test_default_config_patterns_have_no_nested_quantifiers(pattern):
    assert NESTED_QUANTIFIER.search(pattern) is None


def test_default_patterns_are_safe_on_adversarial_headings():
    heading = "acceptance " * 20_000 + "!"
    rx = ExtractionConfig().compiled()
    start = time.perf_counter()
    for pattern in (rx.section, rx.excluded, rx.table_column):
        assert pattern.fullmatch(heading[:200]) is None
    assert time.perf_counter() - start < 1.0


# -- determinism ---------------------------------------------------------------


def _fixture_sources():
    sources = []
    for path in sorted(FIXTURES.glob("*.md")):
        sources.append(src(path.read_text(encoding="utf-8"), source_id=path.stem))
    return sources


def test_repeated_runs_are_byte_identical():
    sources = _fixture_sources()
    first = [repr(EXTRACTOR.extract_report(s)) for s in sources]
    second = [
        repr(DeterministicCriterionExtractor().extract_report(s)) for s in sources
    ]
    assert first == second


def test_extract_sources_is_independent_of_input_order():
    rng = random.Random(1234)
    kinds = list(IntentSourceKind)
    sources = [
        src(
            path.read_text(encoding="utf-8"), kinds[i % len(kinds)], source_id=path.stem
        )
        for i, path in enumerate(sorted(FIXTURES.glob("*.md")))
    ]
    baseline = repr(EXTRACTOR.extract_sources(sources))
    for _ in range(5):
        shuffled = sources[:]
        rng.shuffle(shuffled)
        assert repr(EXTRACTOR.extract_sources(shuffled)) == baseline


def test_ids_are_stable_when_unrelated_text_changes():
    base = "## Acceptance Criteria\n- Users can log in\n"
    edited = "Intro line added\n" + base + "\nfooter\n"
    a = EXTRACTOR.extract(src(base))
    b = EXTRACTOR.extract(src(edited))
    assert [c.id for c in a] == [c.id for c in b]
    assert a[0].span != b[0].span


def test_output_contains_no_wall_clock_values():
    report = EXTRACTOR.extract_report(src("The api must work."))
    (criterion,) = report.criteria
    assert criterion.origin.retrieved_at == src("x").fetched_at


@pytest.mark.parametrize("seed", range(8))
def test_random_garbage_never_raises(seed):
    rng = random.Random(seed)
    alphabet = list("-*+[]x ()#`~|:<>!\n\t1.\r'\"\\") + [
        "Given ",
        "Scenario:",
        "must ",
        "<!--",
        "-->",
    ]
    text = "".join(rng.choice(alphabet) for _ in range(20_000))
    for kind in (IntentSourceKind.PR_BODY, IntentSourceKind.SPEC_FILE):
        report = EXTRACTOR.extract_report(src(text, kind))
        for criterion in report.criteria:
            assert criterion.span.within(text)
