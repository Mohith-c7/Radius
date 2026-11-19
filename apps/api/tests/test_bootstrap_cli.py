"""R3: ``python -m radius_api.bootstrap`` creates the organization row and first key."""

import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from radius_api.bootstrap import ACTOR, main
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.api_keys import ApiKey, ApiKeyAuditEvent
from radius_shared.database.base import Base
from radius_shared.database.models import Organization
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

PEPPER = "pepper-" + "b" * 40
ORG_A = UUID("00000000-0000-4000-8000-0000000000a1")
ORG_B = UUID("00000000-0000-4000-8000-0000000000b2")


@pytest.fixture
def db(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("RADIUS_ENV", "development")
    for name in (
        "RADIUS_API_KEY_PEPPER",
        "API_KEYS",
        "GITHUB_DEFAULT_ORGANIZATION_ID",
        "NEXT_PUBLIC_RADIUS_ORGANIZATION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def _orgs(factory) -> list[Organization]:
    with factory() as session:
        return list(session.scalars(select(Organization)))


def test_creates_organization_then_is_idempotent(db, capsys) -> None:
    assert main(["--organization-id", str(ORG_A), "--name", "Acme"]) == 0
    assert "Created organization" in capsys.readouterr().err
    first = _orgs(db)
    assert [(o.id, o.name) for o in first] == [(ORG_A, "Acme")]

    assert main(["--organization-id", str(ORG_A), "--name", "Other"]) == 0
    captured = capsys.readouterr()
    assert "already exists" in captured.err and captured.out == ""
    again = _orgs(db)
    assert [(o.id, o.name, o.updated_at) for o in again] == [
        (ORG_A, "Acme", first[0].updated_at)
    ]


def test_organization_id_defaults_from_environment(db, monkeypatch) -> None:
    monkeypatch.setenv("NEXT_PUBLIC_RADIUS_ORGANIZATION_ID", str(ORG_B))
    assert main([]) == 0
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(ORG_A))
    assert main([]) == 0  # GITHUB_DEFAULT_ORGANIZATION_ID wins
    assert {o.id for o in _orgs(db)} == {ORG_A, ORG_B}


@pytest.mark.parametrize(
    "argv",
    [
        ["--organization-id", "not-a-uuid"],
        [],  # no id anywhere
        ["--organization-id", str(ORG_A), "--name", "  "],
    ],
)
def test_usage_errors_exit_2_and_write_nothing(db, argv, capsys) -> None:
    assert main(argv) == 2
    assert "error:" in capsys.readouterr().err
    assert _orgs(db) == []


def test_key_creation_refused_without_pepper(db, capsys) -> None:
    assert main(["--organization-id", str(ORG_A), "--create-admin-key", "admin"]) == 2
    captured = capsys.readouterr()
    assert "RADIUS_API_KEY_PEPPER" in captured.err and captured.out == ""
    assert _orgs(db) == []


def test_invalid_scope_rolls_back(db, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    argv = [
        "--organization-id",
        str(ORG_A),
        "--create-admin-key",
        "k",
        "--scopes",
        "root",
    ]
    assert main(argv) == 2
    assert _orgs(db) == []  # one transaction: no half-bootstrapped org


def test_unmigrated_database_is_refused(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'empty.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    assert main(["--organization-id", str(ORG_A)]) == 1
    assert "not migrated" in capsys.readouterr().err
    engine = create_engine(url)
    Organization.__table__.create(engine)  # org table only: key tables still missing
    engine.dispose()
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    assert main(["--organization-id", str(ORG_A), "--create-admin-key", "k"]) == 1
    assert "api_keys" in capsys.readouterr().err


def _bootstrap_key(org: UUID, capsys, name: str = "bootstrap-admin") -> str:
    assert main(["--organization-id", str(org), "--create-admin-key", name]) == 0
    captured = capsys.readouterr()
    assert "shown ONCE" in captured.err
    token = captured.out.strip()
    assert token.startswith("rdk_") and token not in captured.err
    return token


def test_created_key_authenticates_and_stays_in_its_organization(
    db, monkeypatch, capsys, caplog
) -> None:
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    caplog.set_level(logging.DEBUG)
    token_a = _bootstrap_key(ORG_A, capsys)
    token_b = _bootstrap_key(ORG_B, capsys)
    assert token_a not in caplog.text and token_b not in caplog.text

    with db() as session:
        keys = list(session.scalars(select(ApiKey)))
        events = list(session.scalars(select(ApiKeyAuditEvent)))
    assert {(k.organization_id, tuple(k.scopes), k.created_by) for k in keys} == {
        (ORG_A, ("admin",), ACTOR),
        (ORG_B, ("admin",), ACTOR),
    }
    assert [(e.action, e.actor) for e in events] == [("created", ACTOR)] * 2
    assert token_a not in repr([k.key_hash for k in keys])

    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    get_api_settings.cache_clear()
    client = TestClient(create_app())
    client.app.state.container.session_factory = db

    def get(org: UUID, token: str, path: str = "/api/v1/api-keys"):
        headers = {"X-Radius-Organization-Id": str(org), "X-Radius-API-Key": token}
        return client.get(path, headers=headers)

    listed = get(ORG_A, token_a)
    assert listed.status_code == 200
    assert [k["name"] for k in listed.json()["data"]] == ["bootstrap-admin"]
    audit = get(ORG_A, token_a, "/api/v1/api-keys/audit").json()["data"]
    assert [e["actor"] for e in audit] == [ACTOR]
    # Org isolation: org A's key cannot act for org B, and the reverse.
    assert get(ORG_B, token_a).status_code == 403
    assert get(ORG_A, token_b).status_code == 403


def test_rerun_does_not_duplicate_an_active_key(db, monkeypatch, capsys) -> None:
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    _bootstrap_key(ORG_A, capsys)
    assert (
        main(["--organization-id", str(ORG_A), "--create-admin-key", "bootstrap-admin"])
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "" and "no new key created" in captured.err
    with db() as session:
        assert len(list(session.scalars(select(ApiKey)))) == 1
