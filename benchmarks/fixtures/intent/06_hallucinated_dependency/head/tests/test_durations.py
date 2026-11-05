import pytest

from durations import parse_duration, to_seconds


def test_to_seconds():
    assert to_seconds(1, 1, 1) == 3661


def test_parse_hours_and_minutes():
    assert parse_duration("2h30m") == 9000


def test_parse_seconds_only():
    assert parse_duration("45s") == 45


def test_parse_with_spaces():
    assert parse_duration("1h 1m 1s") == 3661


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("abc")


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        parse_duration("")
