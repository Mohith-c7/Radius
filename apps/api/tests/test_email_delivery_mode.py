"""EMAIL_DELIVERY_MODE: ``log`` prints the link instead of sending; ``smtp`` is unchanged."""

from __future__ import annotations

import secrets
import smtplib

import pytest
from app import auth as auth_module
from app import routes_auth
from app.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for name in ("EMAIL_DELIVERY_MODE", "SMTP_USERNAME", "SMTP_PASSWORD", "RADIUS_ENV"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _NoSmtp:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("SMTP must not be contacted in this mode")


def test_log_mode_prints_link_and_skips_smtp(monkeypatch, capsys) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "log")
    monkeypatch.setenv("SMTP_USERNAME", "someone")
    monkeypatch.setenv("SMTP_PASSWORD", "x" * 12)
    monkeypatch.setattr(smtplib, "SMTP", _NoSmtp)
    ok = routes_auth.send_email_message(
        "a@example.com", "Verify", "open http://localhost:3000/verify-email?token=abc", "<p/>"
    )
    out = capsys.readouterr().out
    assert ok is True
    assert "http://localhost:3000/verify-email?token=abc" in out
    assert "EMAIL_DELIVERY_MODE=log" in out


def test_smtp_mode_without_credentials_still_falls_back(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _NoSmtp)
    ok = routes_auth.send_email_message("a@example.com", "s", "secret-link-body", "<p/>")
    out = capsys.readouterr().out
    assert ok is False
    assert "secret-link-body" not in out  # smtp mode never prints the message body


def test_smtp_mode_with_credentials_uses_smtp(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "p" * 12)
    calls: list[str] = []

    class FakeSmtp:
        def __init__(self, host, port) -> None:
            calls.append(f"{host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def starttls(self) -> None: ...
        def login(self, user, password) -> None: ...
        def sendmail(self, sender, to, message) -> None: ...

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    assert routes_auth.send_email_message("a@example.com", "s", "t", "<p/>") is True
    assert calls == ["smtp.gmail.com:587"]


@pytest.mark.parametrize(
    ("env", "mode", "expected"),
    [
        ("production", None, False),
        ("uat", None, False),
        ("development", None, True),
        (None, None, True),
        ("uat", "log", True),
    ],
)
def test_action_token_links_are_logged_only_for_dev(monkeypatch, env, mode, expected) -> None:
    if env:
        monkeypatch.setenv("RADIUS_ENV", env)
        monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(40))  # production refuses the default
    if mode:
        monkeypatch.setenv("EMAIL_DELIVERY_MODE", mode)
    assert auth_module._may_log_action_tokens() is expected
