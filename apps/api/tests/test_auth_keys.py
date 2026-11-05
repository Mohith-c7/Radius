"""PRD-12: managed API key lifecycle, scopes, legacy keys, audit and storage."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from radius_api.api_keys import (
    ALL_SCOPES,
    ApiKeyService,
    InMemoryApiKeyStore,
    SqlAlchemyApiKeyStore,
    aware,
    effective_scopes,
)
from radius_api.auth import ApiPrincipal, required_scope
from radius_api.config import ApiSettings, get_api_settings
from radius_api.main import create_app, warn_deprecated_api_keys
from radius_api.token_fingerprint import (
    fingerprints_match,
    looks_like_managed_token,
    new_token,
    token_fingerprint,
    token_prefix,
)
from radius_shared.database.api_keys import ApiKey, ApiKeyAuditEvent
from radius_shared.database.base import Base
from radius_shared.database.models import Organization
from radius_shared.errors import NotFoundError, ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PEPPER = "pepper-" + "x" * 40
ORG_A = UUID("00000000-0000-4000-8000-00000000000a")
ORG_B = UUID("00000000-0000-4000-8000-00000000000b")
LEGACY_KEY = "legacy" + "-" + "k" * 24


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _service(clock=None, store=None, pepper=PEPPER) -> ApiKeyService:
    return ApiKeyService(
        store or InMemoryApiKeyStore(), pepper=pepper, clock=clock or Clock()
    )


# --- token helpers ---------------------------------------------------------


def test_token_format_and_fingerprint() -> None:
    token, prefix = new_token()
    assert token.startswith(f"rdk_{prefix}_")
    assert token_prefix(token) == prefix
    assert len(token.split("_", 2)[2]) >= 43  # 256-bit secret
    assert looks_like_managed_token(token)
    digest = token_fingerprint(token, PEPPER)
    assert len(digest) == 64
    assert token not in digest
    assert fingerprints_match(digest, token_fingerprint(token, PEPPER))
    assert not fingerprints_match(digest, token_fingerprint(token, PEPPER + "z"))
    assert not fingerprints_match(digest, token_fingerprint(token + "x", PEPPER))


@pytest.mark.parametrize("bad", ["", "rdk_", "rdk__x", "rdk_ab", "abc_def_ghi", "rdk_ab_"])
def test_malformed_tokens_have_no_prefix(bad: str) -> None:
    assert token_prefix(bad) is None


def test_looks_like_managed_token_handles_none() -> None:
    assert not looks_like_managed_token(None)
    assert not looks_like_managed_token("plain")


# --- service ---------------------------------------------------------------


def test_create_stores_only_fingerprint_and_authenticates() -> None:
    store = InMemoryApiKeyStore()
    svc = _service(store=store)
    key, token = svc.create(ORG_A, name="ci", scopes=["ci-upload"], actor="admin")
    assert token not in repr(vars(key)) and token not in key.key_hash
    assert key.key_hash == token_fingerprint(token, PEPPER)
    assert svc.authenticate(ORG_A, token).id == key.id
    # Wrong organization, tampered secret, and malformed tokens all fail.
    assert svc.authenticate(ORG_B, token) is None
    assert svc.authenticate(ORG_A, token + "x") is None
    assert svc.authenticate(ORG_A, "rdk_nope") is None


def test_create_validation() -> None:
    svc = _service()
    with pytest.raises(ValidationError):
        svc.create(ORG_A, name="x", scopes=["root"], actor="a")
    with pytest.raises(ValidationError):
        svc.create(ORG_A, name="x", scopes=[], actor="a")
    with pytest.raises(ValidationError):
        svc.create(
            ORG_A,
            name="x",
            scopes=["read"],
            actor="a",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        _service(pepper="").create(ORG_A, name="x", scopes=["read"], actor="a")


def test_expiry_is_enforced() -> None:
    clock = Clock()
    svc = _service(clock)
    key, token = svc.create(
        ORG_A,
        name="short",
        scopes=["read"],
        actor="a",
        expires_at=clock.now + timedelta(hours=1),
    )
    assert svc.authenticate(ORG_A, token) is not None
    clock.advance(hours=1, seconds=1)
    assert svc.authenticate(ORG_A, token) is None
    with pytest.raises(ValidationError):
        svc.rotate(ORG_A, key.id, actor="a")  # expired keys cannot rotate


def test_revoke_is_immediate_idempotent_and_audited() -> None:
    svc = _service()
    key, token = svc.create(ORG_A, name="k", scopes=["read"], actor="a")
    svc.revoke(ORG_A, key.id, actor="b")
    svc.revoke(ORG_A, key.id, actor="c")
    assert svc.authenticate(ORG_A, token) is None
    actions = [(e.action, e.actor) for e in svc.audit_events(ORG_A)]
    assert actions == [("created", "a"), ("revoked", "b")]


def test_rotation_overlap_window() -> None:
    clock = Clock()
    svc = _service(clock)
    old, old_token = svc.create(ORG_A, name="k", scopes=["write"], actor="a")
    new, new_token_, replaced = svc.rotate(
        ORG_A, old.id, actor="admin", overlap_seconds=600
    )
    assert new.rotated_from_id == old.id and replaced.id == old.id
    assert list(new.scopes) == ["write"] and new.name == "k"
    assert svc.authenticate(ORG_A, old_token) is not None  # inside overlap
    assert svc.authenticate(ORG_A, new_token_) is not None
    clock.advance(seconds=601)
    assert svc.authenticate(ORG_A, old_token) is None
    assert svc.authenticate(ORG_A, new_token_) is not None
    rotated = [e for e in svc.audit_events(ORG_A) if e.action == "rotated"]
    assert rotated[0].detail["replaces"] == str(old.id)


def test_rotation_zero_overlap_and_bounds_and_inherited_expiry() -> None:
    clock = Clock()
    svc = _service(clock)
    soon = clock.now + timedelta(minutes=5)
    old, old_token = svc.create(
        ORG_A, name="k", scopes=["read"], actor="a", expires_at=soon
    )
    new, _, _ = svc.rotate(ORG_A, old.id, actor="a", overlap_seconds=0)
    assert svc.authenticate(ORG_A, old_token) is None
    assert aware(new.expires_at) == soon  # replacement keeps the original expiry
    with pytest.raises(ValidationError):
        svc.rotate(ORG_A, new.id, actor="a", overlap_seconds=-1)
    with pytest.raises(ValidationError):
        svc.rotate(ORG_A, new.id, actor="a", overlap_seconds=10**9)
    # an old key's own earlier expiry is never extended by a long overlap
    other, other_token = svc.create(
        ORG_A, name="o", scopes=["read"], actor="a", expires_at=soon
    )
    svc.rotate(ORG_A, other.id, actor="a", overlap_seconds=86400)
    clock.advance(minutes=6)
    assert svc.authenticate(ORG_A, other_token) is None


def test_tenant_isolation_on_manage_operations() -> None:
    svc = _service()
    key, _ = svc.create(ORG_A, name="k", scopes=["read"], actor="a")
    assert svc.list(ORG_B) == []
    assert svc.audit_events(ORG_B) == []
    with pytest.raises(NotFoundError):
        svc.revoke(ORG_B, key.id, actor="x")
    with pytest.raises(NotFoundError):
        svc.rotate(ORG_B, key.id, actor="x")
    assert [k.id for k in svc.list(ORG_A)] == [key.id]


def test_last_used_write_is_rate_limited() -> None:
    clock = Clock()
    svc = ApiKeyService(
        InMemoryApiKeyStore(), pepper=PEPPER, clock=clock, last_used_interval_seconds=300
    )
    key, token = svc.create(ORG_A, name="k", scopes=["read"], actor="a")
    assert key.last_used_at is None
    svc.authenticate(ORG_A, token)
    first = key.last_used_at
    assert first == clock.now
    clock.advance(seconds=60)
    svc.authenticate(ORG_A, token)
    assert key.last_used_at == first  # not rewritten inside the interval
    clock.advance(seconds=300)
    svc.authenticate(ORG_A, token)
    assert key.last_used_at == clock.now


def test_authenticate_disabled_without_pepper() -> None:
    token, _ = new_token()
    assert _service(pepper="").authenticate(ORG_A, token) is None


def test_scope_expansion_and_mapping() -> None:
    assert effective_scopes({"admin"}) == ALL_SCOPES
    assert effective_scopes({"write"}) == {"read", "write", "ci-upload"}
    assert effective_scopes({"ci-upload"}) == {"ci-upload"}
    assert effective_scopes({"read"}) == {"read"}
    assert effective_scopes({"bogus"}) == frozenset()
    results = f"/api/v1/analyses/{uuid4()}/tests/results"
    assert required_scope("POST", results) == "ci-upload"
    assert required_scope("GET", results) == "read"
    assert required_scope("POST", "/api/v1/coverage") == "ci-upload"
    assert required_scope("GET", "/api/v1/api-keys") == "admin"
    assert required_scope("DELETE", f"/api/v1/api-keys/{uuid4()}") == "admin"
    assert required_scope("POST", "/api/v1/repositories") == "write"
    assert required_scope("GET", "/api/v1/repositories") == "read"


def test_principal_actor_labels() -> None:
    assert ApiPrincipal(organization_id=ORG_A).actor == "legacy-env-key"
    assert ApiPrincipal(organization_id=ORG_A, source="dev").actor == "insecure-dev"
    assert ApiPrincipal(organization_id=ORG_A, key_prefix="ab12").actor == "key:rdk_ab12"


def test_settings_pepper_validation_and_warning(caplog) -> None:
    with pytest.raises(PydanticValidationError):
        ApiSettings(RADIUS_API_KEY_PEPPER="short")
    assert ApiSettings(RADIUS_API_KEY_PEPPER=PEPPER).api_key_pepper == PEPPER
    with caplog.at_level(logging.WARNING):
        warn_deprecated_api_keys(ApiSettings(api_keys=f"{ORG_A}:{LEGACY_KEY}"))
        warn_deprecated_api_keys(ApiSettings(api_keys=""))
    messages = [r.getMessage() for r in caplog.records]
    assert sum("DEPRECATED" in m for m in messages) == 1
    assert LEGACY_KEY not in " ".join(messages)


# --- HTTP ------------------------------------------------------------------


def _headers(org: UUID, key: str) -> dict[str, str]:
    return {"X-Radius-Organization-Id": str(org), "X-Radius-API-Key": key}


def _client(monkeypatch, **env: str) -> TestClient:
    monkeypatch.setenv("RADIUS_ENV", "development")
    monkeypatch.setenv("API_KEYS", f"{ORG_A}:{LEGACY_KEY},{ORG_B}:{LEGACY_KEY}b")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "false")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_api_settings.cache_clear()
    return TestClient(create_app())


def _create(client, org, key, scopes, **extra):
    return client.post(
        "/api/v1/api-keys",
        headers=_headers(org, key),
        json={"name": "k", "scopes": scopes, **extra},
    )


def test_full_lifecycle_over_http(monkeypatch, caplog) -> None:
    client = _client(monkeypatch)
    caplog.set_level(logging.DEBUG)
    # Legacy key bootstraps the first managed admin key.
    created = _create(client, ORG_A, LEGACY_KEY, ["admin"])
    assert created.status_code == 201
    body = created.json()["data"]
    admin_token = body["token"]
    assert body["key"]["prefix"] == "rdk_" + admin_token.split("_")[1]
    assert "key_hash" not in body["key"]

    listed = client.get("/api/v1/api-keys", headers=_headers(ORG_A, admin_token))
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert len(rows) == 1 and "token" not in rows[0] and admin_token not in listed.text
    assert rows[0]["last_used_at"] is not None

    reader = _create(client, ORG_A, admin_token, ["read"]).json()["data"]
    rotated = client.post(
        f"/api/v1/api-keys/{reader['key']['id']}/rotate",
        headers=_headers(ORG_A, admin_token),
        json={"overlap_seconds": 0},
    )
    assert rotated.status_code == 201
    assert rotated.json()["data"]["replaced"]["id"] == reader["key"]["id"]
    # old reader token dead (zero overlap), new one works
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, reader["token"])).status_code == 403
    new_token_ = rotated.json()["data"]["token"]
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, new_token_)).status_code == 200

    revoked = client.delete(
        f"/api/v1/api-keys/{rotated.json()['data']['key']['id']}",
        headers=_headers(ORG_A, admin_token),
    )
    assert revoked.status_code == 200 and revoked.json()["data"]["revoked_at"]
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, new_token_)).status_code == 403

    audit = client.get("/api/v1/api-keys/audit", headers=_headers(ORG_A, admin_token))
    events = audit.json()["data"]
    assert [e["action"] for e in events] == ["created", "created", "rotated", "revoked"]
    assert events[0]["actor"] == "legacy-env-key"
    assert events[1]["actor"].startswith("key:rdk_")

    # plaintext never reaches logs or audit detail
    for secret in (admin_token, reader["token"], new_token_):
        assert secret not in caplog.text
        assert secret not in audit.text


def test_scope_enforcement_on_existing_routes(monkeypatch) -> None:
    client = _client(monkeypatch)
    tokens = {
        scope: _create(client, ORG_A, LEGACY_KEY, [scope]).json()["data"]["token"]
        for scope in ("read", "write", "ci-upload", "admin")
    }
    repo_body = {"provider": "github", "full_name": "o/r"}

    def status_of(method, path, scope, **kw):
        return client.request(
            method, path, headers=_headers(ORG_A, tokens[scope]), **kw
        ).status_code

    assert status_of("GET", "/api/v1/repositories", "read") == 200
    assert status_of("GET", "/api/v1/repositories", "ci-upload") == 403
    assert status_of("POST", "/api/v1/repositories", "read", json=repo_body) == 403
    assert status_of("POST", "/api/v1/repositories", "ci-upload", json=repo_body) == 403
    assert status_of("POST", "/api/v1/repositories", "write", json=repo_body) != 403
    # admin endpoints
    for scope in ("read", "write", "ci-upload"):
        assert status_of("GET", "/api/v1/api-keys", scope) == 403
    assert status_of("GET", "/api/v1/api-keys", "admin") == 200
    # CI upload: ci-upload passes the scope gate (analysis is unknown -> not 403)
    path = f"/api/v1/analyses/{uuid4()}/tests/results"
    assert status_of("POST", path, "ci-upload", json={}) != 403
    assert status_of("POST", path, "read", json={}) == 403


def test_wrong_org_unknown_and_malformed_keys_look_identical(monkeypatch) -> None:
    client = _client(monkeypatch)
    token = _create(client, ORG_A, LEGACY_KEY, ["admin"]).json()["data"]["token"]
    unknown = "rdk_" + "0" * 8 + "_" + "s" * 43
    responses = [
        client.get("/api/v1/api-keys", headers=_headers(ORG_B, token)),
        client.get("/api/v1/api-keys", headers=_headers(ORG_A, unknown)),
        client.get("/api/v1/api-keys", headers=_headers(ORG_A, "rdk_garbage")),
    ]
    assert {r.status_code for r in responses} == {403}
    assert len({r.text for r in responses}) == 1
    # a key from org A can't see org B's keys
    other = _create(client, ORG_B, LEGACY_KEY + "b", ["read"]).json()["data"]["key"]["id"]
    ids = [r["id"] for r in client.get("/api/v1/api-keys", headers=_headers(ORG_A, token)).json()["data"]]
    assert other not in ids
    assert client.delete(f"/api/v1/api-keys/{other}", headers=_headers(ORG_A, token)).status_code == 404


def test_legacy_keys_still_work_with_full_scopes(monkeypatch) -> None:
    client = _client(monkeypatch)
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, LEGACY_KEY)).status_code == 200
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, "wrong")).status_code == 403
    assert client.get("/api/v1/repositories", headers={"X-Radius-Organization-Id": str(ORG_A)}).status_code == 403


def test_managed_keys_disabled_without_pepper(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_API_KEY_PEPPER="")
    response = _create(client, ORG_A, LEGACY_KEY, ["read"])
    assert response.status_code == 422
    assert "RADIUS_API_KEY_PEPPER" in response.text


def test_no_keys_configured_still_fails_closed(monkeypatch) -> None:
    client = _client(monkeypatch, API_KEYS="")
    response = client.get("/api/v1/repositories", headers=_headers(ORG_A, "anything"))
    assert response.status_code == 403
    assert "API_KEYS" in response.text


def test_managed_key_works_without_legacy_keys_and_in_dev_mode(monkeypatch) -> None:
    client = _client(monkeypatch, API_KEYS="", RADIUS_ALLOW_INSECURE_DEV="true")
    # dev mode without pepper env uses the dev pepper; with pepper set it is used
    first = _create(client, ORG_A, "anything", ["admin"]).json()["data"]["token"]
    assert client.get("/api/v1/api-keys", headers=_headers(ORG_A, first)).status_code == 200
    # a presented managed token is still validated in dev mode
    assert client.get("/api/v1/api-keys", headers=_headers(ORG_A, "rdk_bad_token")).status_code == 403


def test_dev_mode_without_pepper_uses_dev_pepper(monkeypatch) -> None:
    client = _client(
        monkeypatch, API_KEYS="", RADIUS_ALLOW_INSECURE_DEV="true", RADIUS_API_KEY_PEPPER=""
    )
    token = _create(client, ORG_A, "anything", ["read"]).json()["data"]["token"]
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, token)).status_code == 200


def test_rate_limiter_buckets_by_managed_key(monkeypatch) -> None:
    client = _client(
        monkeypatch,
        RADIUS_RATE_LIMIT_ENABLED="true",
        RADIUS_RATE_LIMIT_GENERAL="3/60",
        RADIUS_RATE_LIMIT_IP_MULTIPLIER="100",
    )
    token = _create(client, ORG_A, LEGACY_KEY, ["read"]).json()["data"]["token"]
    other = _create(client, ORG_A, LEGACY_KEY, ["read"]).json()["data"]["token"]
    codes = [
        client.get("/api/v1/repositories", headers=_headers(ORG_A, token)).status_code
        for _ in range(5)
    ]
    assert codes[:2] == [200, 200] and 429 in codes
    # the second key has its own bucket
    assert client.get("/api/v1/repositories", headers=_headers(ORG_A, other)).status_code == 200


def test_expiry_over_http(monkeypatch) -> None:
    client = _client(monkeypatch)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert _create(client, ORG_A, LEGACY_KEY, ["read"], expires_at=past).status_code == 422
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    ok = _create(client, ORG_A, LEGACY_KEY, ["read"], expires_at=future)
    assert ok.status_code == 201 and ok.json()["data"]["key"]["expires_at"]


# --- SQL storage -----------------------------------------------------------


@pytest.fixture
def sql_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(
        engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        for org in (ORG_A, ORG_B):
            session.add(Organization(id=org, name=f"org-{org.int % 100}"))
        session.commit()
    return factory


def test_sql_store_lifecycle_isolation_and_hashed_at_rest(sql_session_factory) -> None:
    with sql_session_factory() as session:
        svc = _service(store=SqlAlchemyApiKeyStore(session))
        key, token = svc.create(ORG_A, name="sql", scopes=["read"], actor="a")
        new, new_tok, _ = svc.rotate(ORG_A, key.id, actor="a", overlap_seconds=60)
        svc.revoke(ORG_A, new.id, actor="b")
        session.commit()
    with sql_session_factory() as session:
        svc = _service(store=SqlAlchemyApiKeyStore(session))
        assert svc.authenticate(ORG_A, token) is not None  # naive datetimes from SQLite
        assert svc.authenticate(ORG_A, new_tok) is None
        assert svc.authenticate(ORG_B, token) is None
        assert svc.list(ORG_B) == [] and svc.audit_events(ORG_B) == []
        assert len(svc.list(ORG_A)) == 2
        assert [e.action for e in svc.audit_events(ORG_A)] == [
            "created",
            "rotated",
            "revoked",
        ]
        # plaintext appears in no column of either table
        dump = repr(
            [
                [getattr(r, c.name) for c in r.__table__.columns]
                for r in [*session.scalars(select(ApiKey)), *session.scalars(select(ApiKeyAuditEvent))]
            ]
        )
        assert token not in dump and new_tok not in dump
        assert token.split("_", 2)[2] not in dump


def test_sql_store_rejects_unknown_organization(sql_session_factory) -> None:
    with sql_session_factory() as session:
        svc = _service(store=SqlAlchemyApiKeyStore(session))
        with pytest.raises(NotFoundError):
            svc.create(uuid4(), name="x", scopes=["read"], actor="a")


def test_http_with_sql_backend(monkeypatch, sql_session_factory) -> None:
    client = _client(monkeypatch)
    client.app.state.container.session_factory = sql_session_factory
    admin = _create(client, ORG_A, LEGACY_KEY, ["admin"])
    assert admin.status_code == 201
    token = admin.json()["data"]["token"]
    listed = client.get("/api/v1/api-keys", headers=_headers(ORG_A, token))
    assert listed.status_code == 200
    assert listed.json()["data"][0]["last_used_at"] is not None
    missing = _create(client, uuid4(), LEGACY_KEY, ["read"])
    assert missing.status_code == 403  # unknown org has no legacy key
    bad = client.get("/api/v1/api-keys", headers=_headers(ORG_A, token + "x"))
    assert bad.status_code == 403
