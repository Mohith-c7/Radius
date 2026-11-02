"""Determinism and robustness: the rater never raises and never goes slow."""

from __future__ import annotations

import random
import time

import pytest
from radius_intent.domain import Testability
from radius_intent.infrastructure.testability import (
    MAX_ANALYSED_CHARS,
    DeterministicTestabilityRater,
)

RATER = DeterministicTestabilityRater()

ALPHABET = (
    list("abcdefghijklmnopqrstuvwxyz ABCXYZ0123456789")
    + list("`\"'.,;:!?()[]{}<>/\\_-%*#@\n\t\x00\x07")
    + [
        "\u200b",
        "\u202e",
        "\u2019",
        "\u00e9",
        "\u00df",
        "\u4e2d",
        "\u0416",
        "\U0001f600",
    ]
    + [
        "must ",
        "returns ",
        "404 ",
        "when ",
        "then ",
        "etc ",
        "TBD ",
        "ms ",
        ".py ",
        "`x` ",
    ]
)


def random_text(rng: random.Random) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 300)))


def test_fuzz_never_raises_and_is_deterministic():
    rng = random.Random(20261102)
    for _ in range(600):
        text = random_text(rng)
        first = RATER.rate_text(text)
        assert first == RATER.rate_text(text)
        assert first.rating is not Testability.UNRATED
        assert first.rationale().strip()
        first.to_assessment()
        first.to_dict()
        for reason in first.reasons:
            for span in reason.spans:
                assert 0 <= span.start <= span.end <= len(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "\x00",
        "\n\n\n",
        "\U0001f600" * 50,
        "\u202e" * 10 + "must return 404",
        "a" * 200_000,
        "must returns 404 when " * 20_000,
        "`" * 100_000,
        "a.b." * 50_000,
        "A" + "a" * 100_000,
        "/".join(["seg"] * 50_000),
        "1" * 100_000,
        "( " * 50_000,
        "Aa" * 100_000,
        "a_" * 100_000,
    ],
)
def test_degenerate_and_huge_inputs(text):
    started = time.perf_counter()
    result = RATER.rate_text(text)
    elapsed = time.perf_counter() - started
    assert result.rating is not Testability.UNRATED
    assert elapsed < 3.0
    if len(text) > MAX_ANALYSED_CHARS:
        assert "text_truncated" in result.rule_ids


def test_unicode_normalization_forms_are_stable_enough():
    composed = "Users can reset their pass\u00e9word"
    decomposed = "Users can reset their passe\u0301word"
    assert RATER.rate_text(composed).rating is RATER.rate_text(decomposed).rating


def test_curly_apostrophes_match_like_straight_ones():
    straight = RATER.rate_text("The service doesn't return stale data")
    curly = RATER.rate_text("The service doesn\u2019t return stale data")
    assert straight.rule_ids == curly.rule_ids


def test_two_instances_agree():
    other = DeterministicTestabilityRater()
    for text in ("Users can log in", "Make it nicer", "TBD", "x" * 10_000):
        assert RATER.rate_text(text) == other.rate_text(text)
