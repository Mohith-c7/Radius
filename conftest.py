"""Global test fixtures and environment isolation for Radius monorepo."""

import pytest


@pytest.fixture(autouse=True)
def isolate_monorepo_test_environment(monkeypatch):
    """Ensure tests run against an in-memory, isolated test environment."""

    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    # Most tests exercise the API without secrets; secure defaults are covered
    # explicitly in apps/api/tests/test_secure_defaults.py.
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("GITHUB_APP_ID", "")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "")
    monkeypatch.delenv("GITHUB_INSTALLATION_ID", raising=False)
    yield
