"""The Check Run / PR comment link is built from the configurable DASHBOARD_BASE_URL."""

from __future__ import annotations

import pytest
from radius_worker.config import WorkerSettings

ANALYSIS = "11111111-2222-3333-4444-555555555555"


def _settings(monkeypatch: pytest.MonkeyPatch, value: str | None) -> WorkerSettings:
    if value is None:
        monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("DASHBOARD_BASE_URL", value)
    return WorkerSettings()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://radius.example.com", f"https://radius.example.com/analyses/{ANALYSIS}"),
        ("https://radius.example.com/", f"https://radius.example.com/analyses/{ANALYSIS}"),
        (" http://192.168.1.20:3000// ", f"http://192.168.1.20:3000/analyses/{ANALYSIS}"),
        ("https://demo.example.com/radius", f"https://demo.example.com/radius/analyses/{ANALYSIS}"),
        ("", None),
        ("   ", None),
        ("javascript:alert(1)", None),
        ("dashboard.example.com", None),
        (None, None),
    ],
)
def test_dashboard_analysis_url(monkeypatch, configured, expected) -> None:
    assert _settings(monkeypatch, configured).dashboard_analysis_url(ANALYSIS) == expected
