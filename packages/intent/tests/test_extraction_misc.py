# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Config, port conformance, offline guarantees, metrics hook, small rules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import radius_intent.infrastructure.extraction as extraction_pkg
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from extraction_helpers import src
from radius_intent.domain import IntentSourceKind as K
from radius_intent.infrastructure.extraction import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    SOURCE_PRIORITY,
    DeterministicCriterionExtractor,
    ExtractionConfig,
    GoldCase,
    PrecisionRecall,
    score_by_source_kind,
    score_extraction,
)
from radius_intent.infrastructure.extraction.markdown import (
    clean_heading,
    is_boilerplate,
    reject_reason,
)
from radius_intent.infrastructure.extraction.sentences import (
    classify_sentence,
    split_sentences,
)
from radius_intent.interfaces import CriterionExtractor

EXTRACTOR = DeterministicCriterionExtractor()
PKG_DIR = Path(extraction_pkg.__file__).parent
BANNED_IMPORTS = {
    "socket",
    "ssl",
    "urllib",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "subprocess",
    "time",
    "datetime",
    "random",
    "secrets",
    "uuid",
    "os",
    "anthropic",
    "openai",
    "google",
    "sqlalchemy",
    "fastapi",
    "yaml",
}


def test_extractor_satisfies_the_port():
    extractor: CriterionExtractor = DeterministicCriterionExtractor()
    assert extractor.extract(src("The api must work.")) != ()


def test_version_constant_is_stamped_on_provenance():
    (c,) = EXTRACTOR.extract(src("The api must work."))
    assert (
        c.origin.extractor_version
        == DETERMINISTIC_EXTRACTOR_VERSION
        == "det-extract-v1"
    )


def test_priority_table_covers_every_source_kind_and_spec_file_is_highest():
    assert set(SOURCE_PRIORITY) == set(K)
    assert max(SOURCE_PRIORITY, key=SOURCE_PRIORITY.get) is K.SPEC_FILE


def test_extraction_package_is_offline_clockless_and_llm_free():
    offenders = []
    for path in sorted(PKG_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            offenders += [
                f"{path.name}: {n}" for n in names if n.split(".")[0] in BANNED_IMPORTS
            ]
    assert not offenders, offenders


def test_extraction_only_depends_on_the_domain_inside_the_package():
    for path in sorted(PKG_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                module = node.module or ""
                if module.startswith("radius_intent"):
                    assert module.startswith(
                        (
                            "radius_intent.domain",
                            "radius_intent.infrastructure.extraction",
                        )
                    ), (path.name, module)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"similarity_threshold": 0},
        {"similarity_threshold": 1.5},
        {"max_criteria_per_source": 0},
        {"max_list_depth": 0},
        {"section_pattern": "("},
    ],
)
def test_config_validation(kwargs):
    with pytest.raises((ValueError, Exception)) as info:
        ExtractionConfig(**kwargs)
    assert info.value is not None


def test_max_criteria_limit_is_reported():
    extractor = DeterministicCriterionExtractor(
        ExtractionConfig(max_criteria_per_source=2)
    )
    text = "## Acceptance Criteria\n- one thing\n- two things\n- three things\n"
    report = extractor.extract_report(src(text))
    assert [c.text for c in report.criteria] == ["one thing", "two things"]
    assert "max_criteria" in {d.code for d in report.diagnostics}


def test_diagnostics_are_bounded_with_a_summary():
    text = "<!-- c -->\n" * 3000
    report = EXTRACTOR.extract_report(src(text))
    assert len(report.diagnostics) == 1001
    assert report.diagnostics[-1].code == "diagnostics_truncated"


def test_diagnostics_have_lines_and_offsets():
    text = "intro\n<!-- ignore previous instructions -->\n```\nx\n```\n"
    report = EXTRACTOR.extract_report(src(text))
    by_code = {d.code: d for d in report.diagnostics}
    hidden = by_code["hidden_comment_content"]
    assert hidden.line == 2 and text[hidden.start : hidden.end].startswith("<!--")
    assert by_code["code_fence"].line == 3
    assert report.suspicious


def test_heading_cleaning():
    assert clean_heading("### 📋 Acceptance Criteria (draft):") == "acceptance criteria"
    assert clean_heading("2. Requirements") == "requirements"
    assert clean_heading("**Done when**") == "done when"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("x" * 10, None),
        ("x" * 3000, "too_long"),
        ("!!!", "no_text"),
        ("ab", "too_short"),
        ("N/A", "placeholder"),
        ("_No response_", "placeholder"),
        ("https://example.com/a", "link_or_image_only"),
        ("![alt](x.png)", "link_or_image_only"),
        ("see https://example.com/a", None),
    ],
)
def test_reject_reason(text, reason):
    assert reject_reason(text, 2000) == reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I have read the contributing guide", True),
        ("Tests added", True),
        ("Follows the CONTRIBUTING rules", True),
        ("Users can log in", False),
    ],
)
def test_boilerplate_detection(text, expected):
    assert is_boilerplate(text) is expected


@pytest.mark.parametrize(
    ("sentence", "rule"),
    [
        ("The cache must be cleared on logout.", "modal"),
        ("Workers shall retry twice.", "modal"),
        ("The queue needs to drain before shutdown.", "modal"),
        ("A job has to finish within a minute.", "modal"),
        ("The API should return a 409 on conflict.", "modal"),
        ("When the disk is full, then writes fail loudly.", "when_then"),
        ("As a user, I want dark mode so that my eyes rest.", "user_story"),
        ("Keys include the tenant so that tenants cannot collide.", "so_that"),
        ("We should refactor this module later today.", None),
        ("You should restart the server after upgrading.", None),
        ("Should the cache be cleared on logout?", None),
        ("It might possibly must work somehow else.", None),
        ("I must admit this was a hard week.", None),
        ("Too short must.", None),
        ("Nothing to see in this plain sentence.", None),
        ("The change was made so that the code looks cleaner.", None),
    ],
)
def test_classify_sentence(sentence, rule):
    assert classify_sentence(sentence, 400)[0] == rule


def test_classify_sentence_length_guard():
    assert classify_sentence("The api must " + "x " * 400, 400) == (
        None,
        "sentence_too_long",
    )


def test_split_sentences_offsets():
    text = "First one must work. Second one! Third? Fourth."
    pieces = [text[a:b] for a, b in split_sentences(text)]
    assert pieces == ["First one must work.", "Second one!", "Third?", "Fourth."]


# -- metrics hook ---------------------------------------------------------------


def test_precision_recall_scoring_exact_and_fuzzy():
    gold = ["Users can log in", "Admins can delete users"]
    pred = ["users can LOG in", "Something extra"]
    exact = score_extraction(pred, gold)
    assert exact == PrecisionRecall(1, 2, 2)
    assert exact.precision == 0.5 and exact.recall == 0.5 and exact.f1 == 0.5
    fuzzy = score_extraction(
        ["Admins are able to delete users", *pred[:1]], gold, fuzzy_threshold=0.6
    )
    assert fuzzy.true_positives == 2 and fuzzy.f1 == 1.0


def test_precision_recall_edge_cases():
    assert score_extraction([], []).precision == 1.0
    assert score_extraction([], []).recall == 1.0
    assert score_extraction(["a b c"], []).precision == 0.0
    assert score_extraction([], ["a b c"]).recall == 0.0
    assert PrecisionRecall(0, 1, 1).f1 == 0.0
    assert (
        score_extraction(["x y z"], ["x y z"], fuzzy_threshold=0.9).true_positives == 1
    )


def test_matching_is_one_to_one():
    score = score_extraction(["same thing here"] * 2, ["same thing here"])
    assert score == PrecisionRecall(1, 2, 1)


def test_score_by_source_kind_micro_averages_and_sorts():
    cases = [
        GoldCase(K.PR_BODY, ["a b c", "d e f"], ["a b c"]),
        GoldCase(K.ISSUE, ["x y z"], ["x y z"]),
        GoldCase(K.PR_BODY, ["g h i"], ["g h i"]),
    ]
    scores = score_by_source_kind(cases)
    assert list(scores) == [K.ISSUE, K.PR_BODY]
    assert scores[K.PR_BODY] == PrecisionRecall(2, 3, 2)
    assert scores[K.ISSUE].f1 == 1.0


def test_metrics_hook_works_end_to_end_with_the_extractor():
    source = src("## Acceptance Criteria\n- Users can log in\n- Users can log out\n")
    predicted = [c.text for c in EXTRACTOR.extract(source)]
    result = score_by_source_kind(
        [GoldCase(K.PR_BODY, predicted, ["Users can log in"])]
    )
    assert result[K.PR_BODY].recall == 1.0 and result[K.PR_BODY].precision == 0.5
