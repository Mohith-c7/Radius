"""C-14 (auth engine URL normalisation) and C-20 (configurable session cookie domain)."""

import os
import subprocess
import sys

import app.routes_auth as routes_auth
import pytest
from app.config import Settings
from fastapi import Response


def _engine_facts(database_url: str) -> str:
    code = (
        "import app.database as d; "
        "print(d.engine.url.drivername, d.engine.pool._pre_ping)"
    )
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
    }
    done = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    return done.stdout.strip()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_auth_engine_accepts_postgres_urls_like_the_rest_of_the_platform(scheme) -> None:
    # Before the fix `postgres://` raised NoSuchModuleError at import of app.database.
    facts = _engine_facts(f"{scheme}://user:pw@localhost:5432/radius")
    assert facts == "postgresql+psycopg True"


def test_auth_engine_still_works_for_sqlite() -> None:
    assert _engine_facts("sqlite:///./auth-engine-test.db") == "sqlite True"


def _cookie_header(monkeypatch, **settings) -> str:
    conf = Settings(**settings)
    monkeypatch.setattr(routes_auth, "get_settings", lambda: conf)
    monkeypatch.setattr(routes_auth, "create_session", lambda db, user, remember: "tok")
    response = Response()
    routes_auth.set_session(response, db=None, user=None)
    return response.headers["set-cookie"]


def test_session_cookie_is_host_only_by_default(monkeypatch) -> None:
    header = _cookie_header(monkeypatch)
    assert "Domain=" not in header and "HttpOnly" in header


def test_session_cookie_domain_is_applied_when_configured(monkeypatch) -> None:
    header = _cookie_header(monkeypatch, session_cookie_domain=".Example.com")
    assert "Domain=example.com" in header and "HttpOnly" in header


@pytest.mark.parametrize(
    "bad",
    ["localhost", "10.0.0.1", "example.com:3000", "https://example.com", "a b.com", "-x.example.com", "x..com"],
)
def test_session_cookie_domain_rejects_unsafe_values(bad) -> None:
    with pytest.raises(ValueError):
        Settings(session_cookie_domain=bad)


def test_blank_cookie_domain_means_host_only() -> None:
    assert Settings(session_cookie_domain="  ").session_cookie_domain is None
