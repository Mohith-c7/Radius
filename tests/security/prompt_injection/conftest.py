"""Fixtures for the prompt-injection suite (marker ``prompt_injection``)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:  # tests run with --import-mode=importlib
    sys.path.insert(0, _HERE)

from pi_harness import PLANTED_ENV  # noqa: E402


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(Path(_HERE)):
            item.add_marker(pytest.mark.prompt_injection)


@pytest.fixture(autouse=True)
def planted_env(monkeypatch):
    """Plant fake secrets in os.environ; nothing may ever leak them."""

    for key, value in PLANTED_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(PLANTED_ENV)


@pytest.fixture(scope="session")
def secrets():
    return list(PLANTED_ENV.values())

