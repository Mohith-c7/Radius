"""Global test fixtures and environment isolation for Radius monorepo."""

import pytest
from pydantic_settings import BaseSettings


def _ignore_local_dotenv() -> None:
    """Make every settings class ignore a developer's local ``.env`` file.

    The suite must behave identically whether or not someone copied
    ``.env.example`` to ``.env`` (which carries placeholder SMTP credentials,
    ``RADIUS_ENV=development`` and so on). Settings read ``.env`` only through
    ``model_config["env_file"]``; clearing it on the base classes before the
    application modules are imported means subclasses inherit the change. Real
    process environment variables (and the per-test overrides below) still apply.
    """

    from radius_shared.config import RadiusBaseSettings
    from radius_shared.observability.settings import ObservabilitySettings

    classes: list[type[BaseSettings]] = [RadiusBaseSettings, ObservabilitySettings]
    try:
        from app.config import Settings as AuthSettings

        classes.append(AuthSettings)
    except ImportError:  # apps/api/src not on PYTHONPATH for this invocation
        pass
    for cls in classes:
        cls.model_config["env_file"] = None


_ignore_local_dotenv()


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
