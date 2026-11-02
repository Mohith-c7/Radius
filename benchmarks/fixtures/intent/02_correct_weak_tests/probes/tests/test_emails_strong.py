import pytest

from emails import normalize_email


def test_probe_normalize_lowercases_and_trims():
    assert normalize_email("  Ann@Example.COM ") == "ann@example.com"


def test_probe_normalize_rejects_missing_at():
    with pytest.raises(ValueError):
        normalize_email("not-an-email")
