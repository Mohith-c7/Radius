"""Unit tests for the pure parts of scripts/load_test.py (no network)."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_test.py"
_spec = importlib.util.spec_from_file_location("load_test", _SCRIPT)
lt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = lt
_spec.loader.exec_module(lt)


def test_percentiles_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]
    assert lt.percentile(values, 50) == 50.0
    assert lt.percentile(values, 95) == 95.0
    assert lt.percentile(values, 99) == 99.0
    assert lt.percentile([7.0], 99) == 7.0
    assert lt.percentile([], 50) == 0.0
    assert lt.percentile([3.0, 1.0, 2.0], 100) == 3.0


def test_signing_matches_github_scheme() -> None:
    body = b'{"a":1}'
    expected = "sha256=" + hmac.new(b"s3", body, hashlib.sha256).hexdigest()
    assert lt.sign_payload("s3", body) == expected
    payload, headers = lt.ping_request("s3")
    assert headers["X-Hub-Signature-256"] == lt.sign_payload("s3", payload)
    assert headers["X-GitHub-Event"] == "ping"


def test_summarize() -> None:
    stats = lt.summarize([10.0, 20.0, 30.0, 40.0], errors=1, elapsed_s=2.0)
    assert stats["error_rate"] == 0.25
    assert stats["rps"] == 2.0
    assert stats["p50_ms"] == 20.0


def test_budget_parse_and_check() -> None:
    budget = lt.parse_budget("p95_ms=100, error_rate=0.01")
    assert budget == {"p95_ms": 100.0, "error_rate": 0.01}
    ok = {"a": {"p95_ms": 90.0, "error_rate": 0.0}}
    bad = {"a": {"p95_ms": 150.0, "error_rate": 0.5}}
    assert lt.check_budget(ok, budget) == []
    assert len(lt.check_budget(bad, budget)) == 2
    with pytest.raises(ValueError):
        lt.parse_budget("nonsense=1")


def test_refuses_remote_host() -> None:
    assert lt.main(["--base-url", "http://example.com:8000"]) == 2
    assert lt.main(["--budget", "bad"]) == 2
