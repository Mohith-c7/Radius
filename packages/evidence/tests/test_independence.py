"""EV-03-lite: independence factor table, reasons, agent-trailer detection."""

from __future__ import annotations

import pytest
from radius_evidence.domain.config import QualityConfig
from radius_evidence.domain.enums import AuthoredBy, IndependenceBasis
from radius_evidence.domain.independence import (
    classify_independence,
    detect_agent_trailers,
)

T = "tests/t.py::test_a"


@pytest.mark.parametrize(
    ("kwargs", "authored", "basis", "factor"),
    [
        ({}, AuthoredBy.UNKNOWN, IndependenceBasis.PRE_EXISTING_UNCHANGED, 1.0),
        (
            {"agent_signal": True},
            AuthoredBy.UNKNOWN,
            IndependenceBasis.PRE_EXISTING_UNCHANGED,
            1.0,
        ),
        (
            {"human_attested": True},
            AuthoredBy.HUMAN,
            IndependenceBasis.PRE_EXISTING_UNCHANGED,
            1.0,
        ),
        (
            {"changed_test_ids": {T}},
            AuthoredBy.UNKNOWN,
            IndependenceBasis.CHANGED_IN_PR,
            0.8,
        ),
        (
            {"added_test_ids": {T}},
            AuthoredBy.UNKNOWN,
            IndependenceBasis.CHANGED_IN_PR,
            0.8,
        ),
        (
            {"changed_test_ids": {T}, "agent_signal": True},
            AuthoredBy.AGENT,
            IndependenceBasis.CHANGED_IN_PR,
            0.6,
        ),
        (
            {"added_test_ids": {T}, "agent_signal": True},
            AuthoredBy.AGENT,
            IndependenceBasis.CHANGED_IN_PR,
            0.6,
        ),
        (
            {"changed_test_ids": {T}, "human_attested": True},
            AuthoredBy.HUMAN,
            IndependenceBasis.CHANGED_IN_PR,
            1.0,
        ),
        (
            {"changed_test_ids": {T}, "agent_signal": True, "human_attested": True},
            AuthoredBy.AGENT,
            IndependenceBasis.CHANGED_IN_PR,
            0.6,
        ),
        (
            {"changed_test_ids": {"other"}},
            AuthoredBy.UNKNOWN,
            IndependenceBasis.PRE_EXISTING_UNCHANGED,
            1.0,
        ),
        (
            {"changed_test_ids": {T}, "implementation_changed": True},
            AuthoredBy.UNKNOWN,
            IndependenceBasis.CHANGED_IN_PR,
            0.8,
        ),
    ],
)
def test_factor_table(
    kwargs: dict, authored: AuthoredBy, basis: IndependenceBasis, factor: float
) -> None:
    info = classify_independence(T, **kwargs)
    assert (info.authored_by, info.basis, info.factor) == (authored, basis, factor)
    assert info.reasons  # always explained


@pytest.mark.parametrize(
    ("kwargs", "codes"),
    [
        ({}, {"pre_existing_unchanged"}),
        ({"added_test_ids": {T}}, {"test_added_in_pr", "author_unknown"}),
        ({"changed_test_ids": {T}}, {"test_modified_in_pr", "author_unknown"}),
        (
            {"changed_test_ids": {T}, "agent_signal": True},
            {"test_modified_in_pr", "agent_trailer"},
        ),
        (
            {"changed_test_ids": {T}, "human_attested": True},
            {"test_modified_in_pr", "human_attested"},
        ),
        (
            {"added_test_ids": {T}, "implementation_changed": True},
            {"test_added_in_pr", "implementation_changed_in_pr", "author_unknown"},
        ),
    ],
)
def test_reason_codes(kwargs: dict, codes: set[str]) -> None:
    assert {r.code for r in classify_independence(T, **kwargs).reasons} == codes


def test_implementation_change_does_not_alter_the_factor() -> None:
    a = classify_independence(T, changed_test_ids={T})
    b = classify_independence(T, changed_test_ids={T}, implementation_changed=True)
    assert a.factor == b.factor


def test_custom_factors_are_used() -> None:
    cfg = QualityConfig(
        iota_agent=0.3,
        iota_unknown=0.5,
        iota_human=0.9,
        pre_existing_unchanged_factor=0.95,
    )
    assert classify_independence(T, config=cfg).factor == 0.95
    assert classify_independence(T, changed_test_ids={T}, config=cfg).factor == 0.5
    assert (
        classify_independence(
            T, changed_test_ids={T}, agent_signal=True, config=cfg
        ).factor
        == 0.3
    )
    assert (
        classify_independence(
            T, changed_test_ids={T}, human_attested=True, config=cfg
        ).factor
        == 0.9
    )


def test_agent_never_more_independent_than_unknown_than_pre_existing() -> None:
    pre = classify_independence(T).factor
    unk = classify_independence(T, changed_test_ids={T}).factor
    agent = classify_independence(T, changed_test_ids={T}, agent_signal=True).factor
    assert agent <= unk <= pre


@pytest.mark.parametrize(
    ("message", "detected"),
    [
        ("feat: x\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>", True),
        ("co-authored-by: claude <x@y>", True),
        ("CO-AUTHORED-BY:   CLAUDE", True),
        ("Co-Authored-By: Copilot <copilot@github.com>", True),
        ("Generated with [Claude Code](https://claude.com/claude-code)", True),
        ("Merge branch main\n\nrenovate[bot] update", True),
        ("dependabot[bot] bump", True),
        ("fix: handle empty list", False),
        ("Co-Authored-By: Alice <alice@example.com>", False),
        ("claude is mentioned but not as trailer", False),
        ("", False),
    ],
)
def test_trailer_detection_default_patterns(message: str, detected: bool) -> None:
    assert detect_agent_trailers([message]).detected is detected


def test_trailer_detection_over_many_messages_and_matches_sorted() -> None:
    sig = detect_agent_trailers(
        ["fix a", "bot[bot] x", "Co-Authored-By: Claude", "fix b"]
    )
    assert sig.detected
    assert sig.matches == ("[bot]", "co-authored-by: claude")


def test_trailer_detection_is_total() -> None:
    assert not detect_agent_trailers([]).detected
    assert not detect_agent_trailers([None, 5, b"x"]).detected  # type: ignore[list-item]
    assert not detect_agent_trailers(["anything"], patterns=[]).detected
    assert not detect_agent_trailers(["anything"], patterns=["", "  "]).detected
    assert detect_agent_trailers(["Made by AGENT-X"], patterns=["agent-x"]).detected


def test_trailer_detection_deterministic() -> None:
    msgs = ["Co-Authored-By: Claude", "[bot]"]
    assert detect_agent_trailers(msgs) == detect_agent_trailers(list(reversed(msgs)))
