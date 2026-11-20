"""RADIUS_FEATURE_VERDICT_V2 values wrapped in quotes by an env-file loader."""

from __future__ import annotations

from radius_shared.verdict_v2_flag import VerdictV2Mode, _unquote, parse_verdict_v2_mode


def test_quoted_value_is_read_without_its_quotes() -> None:
    """A quoted "on" or 'shadow' is accepted and read without its quotes."""

    assert parse_verdict_v2_mode('"on"') == VerdictV2Mode.ON
    assert parse_verdict_v2_mode("'shadow'") == VerdictV2Mode.SHADOW
    assert parse_verdict_v2_mode('"off"') == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode('"YES"') == VerdictV2Mode.ON
    assert parse_verdict_v2_mode(' "true" ') == VerdictV2Mode.ON
    assert parse_verdict_v2_mode('" shadow "') == VerdictV2Mode.SHADOW


def test_unrecognised_quoted_value_is_parsed_as_off() -> None:
    """Without its quotes a typo is still unrecognised, so it never switches Verdict v2 on."""

    assert _unquote('"typo"') == "typo"
    assert parse_verdict_v2_mode('"typo"') == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode("'enabled'") == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode('""') == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode('"') == VerdictV2Mode.OFF


def test_unbalanced_or_mismatched_quotes_are_parsed_as_off() -> None:
    """Only one pair of matching surrounding quotes is dropped; anything else stays off."""

    assert _unquote('""on""') == '"on"'
    assert _unquote("\"on'") == "\"on'"
    assert _unquote('"on') == '"on'
    assert _unquote("") == ""
    assert parse_verdict_v2_mode('"on') == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode("on'") == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode("\"on'") == VerdictV2Mode.OFF
    assert parse_verdict_v2_mode('""on""') == VerdictV2Mode.OFF


def test_unquote_drops_one_pair_of_matching_surrounding_quotes() -> None:
    """One pair of matching surrounding quotes is dropped, unbalanced quotes are kept."""

    assert _unquote('"on"') == "on"
    assert _unquote("'shadow'") == "shadow"
    assert _unquote("'\"on\"'") == '"on"'
    assert _unquote('"') == '"'
    assert _unquote("on'") == "on'"
