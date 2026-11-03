"""OAuth/OIDC sign-in against a local stub IdP (no network, keys generated at runtime)."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from app import oauth
from app.auth import hash_password, user_from_provider
from app.config import Settings, get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import AuthAccount, AuthOAuthFlow
from app.models import User as AuthUser
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from radius_api.main import create_app
from radius_api.middleware.rate_limit import classify_request
from radius_shared.database.base import Base as DomainBase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

IDP = "https://idp.test"
FRONTEND = "http://127.0.0.1:3000"
GOOGLE_CB = "http://localhost:8000/api/v1/auth/oauth/google/callback"
GITHUB_CB = "http://localhost:8000/api/v1/auth/oauth/github/callback"
CB = "/api/v1/auth/oauth/{}/callback"

_KEYS: dict[str, Any] = {}


def _key(name: str) -> Any:
    """RSA keys are generated at runtime (once per test session); nothing is stored in the repo."""
    if name not in _KEYS:
        _KEYS[name] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _KEYS[name]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class StubIdP:
    """authorize / token / jwks / userinfo endpoints for both stub providers."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.kids = {"kid-1": "k1"}
        self.active_kid = "kid-1"
        self.sign_key = None  # override: key used to sign (default: the active kid's key)
        self.codes: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.token_requests: list[dict[str, str]] = []
        self.claims: dict[str, Any] = {}
        self.drop_claims: set[str] = set()
        self.id_token_override: str | None = None
        self.token_mode = "ok"  # ok | http400 | http500 | error200 | notjson | no_id_token | raise
        self.jwks_mode = "ok"  # ok | http500 | badjson | raise
        self.challenge_override: str | None = None
        self.sub = "g-sub-1001"
        self.email = "alice@example.com"
        self.github_id = 4242
        self.github_profile_email = None
        self.github_emails: Any = [
            {"email": "alice@example.com", "primary": True, "verified": True}
        ]
        self.access_token = "gho_" + secrets.token_hex(16)

    # -- browser side ---------------------------------------------------------
    def authorize(self, location: str) -> tuple[str, str]:
        """Pretend to be the IdP + user consent. Returns (code, state)."""
        parts = urlsplit(location)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" in {
            f"{IDP}/google/authorize",
            f"{IDP}/github/authorize",
        }
        assert query["client_id"] == self.client_id
        assert query["response_type"] == "code"
        assert query["redirect_uri"] in {GOOGLE_CB, GITHUB_CB}
        code = secrets.token_urlsafe(16)
        self.codes[code] = {
            "challenge": self.challenge_override or query.get("code_challenge"),
            "method": query.get("code_challenge_method"),
            "nonce": query.get("nonce"),
            "redirect_uri": query["redirect_uri"],
            "used": False,
            "kind": "google" if "/google/" in parts.path else "github",
        }
        return code, query["state"]

    # -- tokens ---------------------------------------------------------------
    def make_id_token(self, nonce: str | None, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "https://accounts.google.com",
            "aud": self.client_id,
            "sub": self.sub,
            "email": self.email,
            "email_verified": True,
            "name": "Alice Example",
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
        }
        claims.update(self.claims)
        claims.update(overrides)
        for name in self.drop_claims:
            claims.pop(name, None)
        kid = self.active_kid
        key = self.sign_key or _key(self.kids[kid])
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})

    def _jwks(self) -> dict[str, Any]:
        keys = []
        for kid, name in self.kids.items():
            jwk = json.loads(RSAAlgorithm.to_jwk(_key(name).public_key()))
            jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
            keys.append(jwk)
        return {"keys": keys}

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        mode = self.token_mode
        if mode == "raise":
            raise httpx.ConnectError("boom", request=request)
        if mode == "http500":
            return httpx.Response(500, text="oops")
        if mode == "http400":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if mode == "error200":
            return httpx.Response(200, json={"error": "bad_verification_code"})
        if mode == "notjson":
            return httpx.Response(200, text="<html>nope</html>")
        entry = self.codes.get(form.get("code", ""))
        if (
            entry is None
            or entry["used"]
            or form.get("client_secret") != self.client_secret
            or form.get("client_id") != self.client_id
            or form.get("redirect_uri") != entry["redirect_uri"]
            or form.get("grant_type") != "authorization_code"
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        entry["used"] = True
        if entry["challenge"] is not None:
            verifier = form.get("code_verifier", "")
            expected = _b64(hashlib.sha256(verifier.encode()).digest())
            if entry["method"] != "S256" or not hmac.compare_digest(expected, entry["challenge"]):
                return httpx.Response(400, json={"error": "invalid_grant"})
        body: dict[str, Any] = {"access_token": self.access_token, "token_type": "Bearer"}
        if entry["kind"] == "google" and mode != "no_id_token":
            body["id_token"] = self.id_token_override or self.make_id_token(entry["nonce"])
        return httpx.Response(200, json=body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path
        self.calls.append((request.method, f"{url.scheme}://{url.host}{path}"))
        if url.host != "idp.test":
            raise AssertionError(f"unexpected host {url.host}")  # no real network
        if request.method == "POST" and path in {"/google/token", "/github/token"}:
            return self._token(request)
        if path == "/jwks":
            if self.jwks_mode == "raise":
                raise httpx.ConnectError("jwks down", request=request)
            if self.jwks_mode == "http500":
                return httpx.Response(500)
            if self.jwks_mode == "badjson":
                return httpx.Response(200, text="{not json")
            return httpx.Response(200, json=self._jwks())
        auth = request.headers.get("authorization", "")
        if path in {"/user", "/user/emails"}:
            if auth != f"Bearer {self.access_token}":
                return httpx.Response(401)
            if path == "/user":
                return httpx.Response(
                    200,
                    json={
                        "id": self.github_id,
                        "login": "alice-gh",
                        "name": "Alice GH",
                        "email": self.github_profile_email,
                    },
                )
            return httpx.Response(200, json=self.github_emails)
        return httpx.Response(404)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    DomainBase.metadata.create_all(bind=eng)
    AuthBase.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def idp(monkeypatch):
    client_id = "cid-" + secrets.token_hex(6)
    client_secret = secrets.token_hex(16)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", GOOGLE_CB)
    monkeypatch.setenv("GITHUB_CLIENT_ID", client_id)
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("GITHUB_REDIRECT_URI", GITHUB_CB)
    monkeypatch.setenv("FRONTEND_ORIGIN", FRONTEND)
    monkeypatch.setenv("RADIUS_ENV", "development")
    monkeypatch.setenv("RADIUS_RATE_LIMIT_AUTH", "1000/60")  # re-set in the rate-limit test
    get_settings.cache_clear()
    stub = StubIdP(client_id, client_secret)
    providers = {
        "google": dataclasses.replace(
            oauth.PROVIDERS["google"],
            authorize_url=f"{IDP}/google/authorize",
            token_url=f"{IDP}/google/token",
            jwks_url=f"{IDP}/jwks",
        ),
        "github": dataclasses.replace(
            oauth.PROVIDERS["github"],
            authorize_url=f"{IDP}/github/authorize",
            token_url=f"{IDP}/github/token",
            profile_url=f"{IDP}/user",
            emails_url=f"{IDP}/user/emails",
        ),
    }
    monkeypatch.setattr(oauth, "PROVIDERS", providers)
    monkeypatch.setattr(
        oauth,
        "make_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(stub.handler)),
    )
    oauth.JWKS_CACHE.reset()
    yield stub
    oauth.JWKS_CACHE.reset()
    get_settings.cache_clear()


@pytest.fixture
def make_client(engine, idp):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    clients = []

    def _make() -> TestClient:
        app = create_app()

        def override():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


def begin(client: TestClient, idp: StubIdP, provider: str = "google", next_: str | None = None):
    params = {"next": next_} if next_ is not None else None
    start = client.get(f"/api/v1/auth/oauth/{provider}", params=params)
    assert start.status_code == 307, start.text
    code, state = idp.authorize(start.headers["location"])
    return start, code, state


def finish(client: TestClient, provider: str, code: str | None, state: str | None, **extra):
    params = {k: v for k, v in {"code": code, "state": state, **extra}.items() if v is not None}
    return client.get(CB.format(provider), params=params)


def sign_in(client, idp, provider="google", next_=None):
    _, code, state = begin(client, idp, provider, next_)
    return finish(client, provider, code, state)


def error_of(response) -> str:
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith(f"{FRONTEND}/login?error="), location
    assert "radius_session" not in response.headers.get("set-cookie", "")
    return location.split("error=")[1]


def count_users(db) -> int:
    return len(db.scalars(select(AuthUser)).all())


# ------------------------------------------------------------------ happy path / PKCE


def test_google_happy_path_with_pkce_state_nonce(client, idp, db):
    start = client.get("/api/v1/auth/oauth/google")
    query = {k: v[0] for k, v in parse_qs(urlsplit(start.headers["location"]).query).items()}
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    assert query["nonce"] and query["state"] and query["redirect_uri"] == GOOGLE_CB
    assert query["scope"] == "openid email profile"
    flow_cookie = start.headers["set-cookie"].lower()
    assert "httponly" in flow_cookie and "samesite=lax" in flow_cookie
    assert "path=/api/v1/auth/oauth" in flow_cookie
    row = db.scalars(select(AuthOAuthFlow)).one()
    assert query["state"] not in (row.state_hash, row.flow_hash)  # only hashes at rest
    assert oauth.pkce_challenge(row.code_verifier) == query["code_challenge"]
    assert row.code_verifier not in start.headers["location"]
    assert row.nonce == query["nonce"]

    code, state = idp.authorize(start.headers["location"])
    done = finish(client, "google", code, state)
    assert done.status_code == 307
    assert done.headers["location"] == f"{FRONTEND}/"
    assert "radius_session=" in done.headers["set-cookie"]
    assert done.headers["cache-control"] == "no-store"
    assert idp.token_requests[0]["code_verifier"] == row.code_verifier
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "alice@example.com"
    assert me.json()["email_verified"] is True
    account = db.scalars(select(AuthAccount)).one()
    assert (account.provider, account.provider_account_id) == ("google", "g-sub-1001")
    assert db.scalars(select(AuthOAuthFlow)).all() == []  # single use: row gone
    assert {u for _, u in idp.calls if u.startswith("http")} <= {
        f"{IDP}/google/token",
        f"{IDP}/jwks",
    }


def test_state_and_pkce_are_random_per_flow(client, idp, db):
    client.get("/api/v1/auth/oauth/google")
    client.get("/api/v1/auth/oauth/google")
    rows = db.scalars(select(AuthOAuthFlow)).all()
    assert len({r.state_hash for r in rows}) == 2
    assert len({r.code_verifier for r in rows}) == 2
    assert len({r.nonce for r in rows}) == 2


def test_pkce_challenge_matches_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert oauth.pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_verifier_mismatch_is_rejected_by_token_endpoint(client, idp, db):
    idp.challenge_override = _b64(hashlib.sha256(b"someone else's verifier").digest())
    assert error_of(sign_in(client, idp)) == "oauth"
    assert db.scalars(select(AuthAccount)).all() == []


# ------------------------------------------------------------------------ state


def test_replayed_callback_is_rejected(client, idp, db):
    _, code, state = begin(client, idp)
    assert finish(client, "google", code, state).headers["location"] == f"{FRONTEND}/"
    replay = finish(client, "google", code, state)
    assert error_of(replay) == "oauth"
    assert len(idp.token_requests) == 1  # never reached the token endpoint again


def test_wrong_state_is_rejected_and_burns_the_flow(client, idp, db):
    _, code, state = begin(client, idp)
    assert error_of(finish(client, "google", code, state + "x")) == "oauth"
    assert idp.token_requests == []
    assert db.scalars(select(AuthOAuthFlow)).all() == []
    assert error_of(finish(client, "google", code, state)) == "oauth"  # retry with right state


def test_missing_state_or_code_is_rejected(client, idp):
    _, code, state = begin(client, idp)
    assert error_of(finish(client, "google", code, None)) == "oauth"
    _, code, state = begin(client, idp)
    assert error_of(finish(client, "google", None, state)) == "oauth"
    assert idp.token_requests == []


def test_state_from_another_browser_without_flow_cookie_is_rejected(make_client, idp):
    victim, attacker = make_client(), make_client()
    _, code, state = begin(attacker, idp)  # attacker starts a flow, tricks victim into the callback
    assert error_of(finish(victim, "google", code, state)) == "oauth"
    assert idp.token_requests == []


def test_expired_flow_is_rejected(client, idp, db):
    _, code, state = begin(client, idp)
    row = db.scalars(select(AuthOAuthFlow)).one()
    row.expires_at = row.expires_at.replace(year=2000)
    db.commit()
    assert error_of(finish(client, "google", code, state)) == "oauth"
    assert idp.token_requests == []


def test_flow_for_another_provider_is_rejected(client, idp):
    _, code, state = begin(client, idp, "google")
    assert error_of(finish(client, "github", code, state)) == "oauth"
    assert idp.token_requests == []


def test_provider_error_is_reported_without_exchanging(client, idp):
    _, _, state = begin(client, idp)
    done = finish(client, "google", None, state, error="access_denied")
    assert error_of(done) == "oauth_denied"
    assert idp.token_requests == []


# ------------------------------------------------------------------- ID token


def test_nonce_mismatch(client, idp):
    idp.claims = {"nonce": "attacker-nonce"}
    assert error_of(sign_in(client, idp)) == "oauth"


def test_missing_nonce(client, idp):
    idp.drop_claims = {"nonce"}
    assert error_of(sign_in(client, idp)) == "oauth"


def test_bad_signature(client, idp, db):
    idp.sign_key = _key("attacker")  # right kid, wrong key
    assert error_of(sign_in(client, idp)) == "oauth"
    assert count_users(db) == 0


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "some-other-client"},
        {"aud": ["some-other-client", "x"]},
        {"iss": "https://evil.example"},
        {"iss": "https://accounts.google.com.evil.example"},
        {"exp": int(time.time()) - 3600},
        {"iat": int(time.time()) + 3600, "exp": int(time.time()) + 7200},
        {"sub": ""},
    ],
)
def test_invalid_claims_rejected(client, idp, db, claims):
    idp.claims = claims
    assert error_of(sign_in(client, idp)) == "oauth"
    assert count_users(db) == 0


@pytest.mark.parametrize("missing", ["exp", "iat", "iss", "aud", "sub"])
def test_missing_required_claims_rejected(client, idp, missing):
    idp.drop_claims = {missing}
    assert error_of(sign_in(client, idp)) == "oauth"


def test_multiple_audiences_require_matching_azp(client, idp):
    idp.claims = {"aud": [idp.client_id, "other"], "azp": "other"}
    assert error_of(sign_in(client, idp)) == "oauth"


def test_alg_none_is_rejected(client, idp, db):
    def forge(nonce):
        header = _b64(json.dumps({"alg": "none", "kid": "kid-1", "typ": "JWT"}).encode())
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com", "aud": idp.client_id, "sub": "evil",
            "email": "alice@example.com", "email_verified": True,
            "iat": now, "exp": now + 300, "nonce": nonce,
        }  # fmt: skip
        return f"{header}.{_b64(json.dumps(claims).encode())}."

    start, code, state = begin(client, idp)
    nonce = parse_qs(urlsplit(start.headers["location"]).query)["nonce"][0]
    idp.id_token_override = forge(nonce)
    assert error_of(finish(client, "google", code, state)) == "oauth"
    assert count_users(db) == 0


def test_hs256_with_public_key_as_secret_is_rejected(client, idp, db):
    public_pem = _key("k1").public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    start, code, state = begin(client, idp)
    nonce = parse_qs(urlsplit(start.headers["location"]).query)["nonce"][0]
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "kid": "kid-1", "typ": "JWT"}).encode())
    claims = _b64(
        json.dumps(
            {"iss": "https://accounts.google.com", "aud": idp.client_id, "sub": "evil",
             "email": "alice@example.com", "email_verified": True, "iat": now,
             "exp": now + 300, "nonce": nonce}  # fmt: skip
        ).encode()
    )
    mac = hmac.new(public_pem, f"{header}.{claims}".encode(), hashlib.sha256).digest()
    idp.id_token_override = f"{header}.{claims}.{_b64(mac)}"
    assert error_of(finish(client, "google", code, state)) == "oauth"
    assert count_users(db) == 0


def test_missing_id_token_and_garbage_id_token(client, idp):
    idp.token_mode = "no_id_token"
    assert error_of(sign_in(client, idp)) == "oauth"
    idp.token_mode = "ok"
    idp.id_token_override = "not-a-jwt"
    assert error_of(sign_in(client, idp)) == "oauth"


def test_email_verified_must_be_true(client, idp, db):
    for value in (False, "true", "false", None, 1):
        idp.claims = {"email_verified": value}
        assert error_of(sign_in(client, idp)) == "oauth_email_unverified"
    idp.claims = {}
    idp.drop_claims = {"email_verified"}
    assert error_of(sign_in(client, idp)) == "oauth_email_unverified"
    idp.drop_claims = {"email"}
    assert error_of(sign_in(client, idp)) == "oauth_email_unverified"
    assert count_users(db) == 0


# --------------------------------------------------------- token endpoint / JWKS


@pytest.mark.parametrize("mode", ["http400", "http500", "error200", "notjson", "raise"])
def test_token_endpoint_failures(client, idp, db, mode):
    idp.token_mode = mode
    assert error_of(sign_in(client, idp)) == "oauth"
    assert count_users(db) == 0


@pytest.mark.parametrize("mode", ["http500", "badjson", "raise"])
def test_jwks_failures_reject_sign_in(client, idp, db, mode):
    idp.jwks_mode = mode
    assert error_of(sign_in(client, idp)) == "oauth"
    assert count_users(db) == 0


def test_jwks_is_cached_and_rotation_is_picked_up(client, idp, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(oauth.JWKS_CACHE, "_clock", clock)
    assert sign_in(client, idp).headers["location"] == f"{FRONTEND}/"
    assert sign_in(client, idp).headers["location"] == f"{FRONTEND}/"
    assert [u for _, u in idp.calls].count(f"{IDP}/jwks") == 1  # cached

    idp.kids["kid-2"] = "k2"  # provider rotates and signs with the new key
    idp.active_kid = "kid-2"
    clock.now += 5  # unknown kid but a refetch just happened: rate limited
    assert error_of(sign_in(client, idp)) == "oauth"
    assert [u for _, u in idp.calls].count(f"{IDP}/jwks") == 1
    clock.now += oauth.JWKS_MIN_REFETCH_SECONDS + 1
    assert sign_in(client, idp).headers["location"] == f"{FRONTEND}/"
    assert [u for _, u in idp.calls].count(f"{IDP}/jwks") == 2


def test_unknown_kid_is_rejected(client, idp):
    idp.kids["kid-9"] = "k2"
    idp.active_kid = "kid-9"
    idp.sign_key = _key("k2")
    # make the JWKS not list kid-9 although the token names it
    original = idp._jwks
    idp._jwks = lambda: {"keys": [k for k in original()["keys"] if k["kid"] != "kid-9"]}
    assert error_of(sign_in(client, idp)) == "oauth"


# ------------------------------------------------------------- account linking


def test_unverified_local_account_is_never_linked(client, idp, db):
    local = AuthUser(
        name="Alice", email="alice@example.com", email_verified=False,
        password_hash=hash_password("Attacker1pass"),
    )  # fmt: skip
    db.add(local)
    db.commit()
    assert error_of(sign_in(client, idp)) == "oauth_link_refused"
    assert db.scalars(select(AuthAccount)).all() == []
    assert count_users(db) == 1
    assert client.get("/api/v1/auth/me").status_code == 401


def test_verified_local_account_is_linked_when_provider_verified(client, idp, db):
    local = AuthUser(name="Alice", email="alice@example.com", email_verified=True)
    db.add(local)
    db.commit()
    local_id = local.id
    assert sign_in(client, idp).headers["location"] == f"{FRONTEND}/"
    assert client.get("/api/v1/auth/me").json()["id"] == local_id
    account = db.scalars(select(AuthAccount)).one()
    assert account.user_id == local_id and account.provider_account_id == "g-sub-1001"


def test_identity_is_keyed_by_provider_and_sub_not_email(client, idp, db):
    sign_in(client, idp)
    first_id = client.get("/api/v1/auth/me").json()["id"]
    idp.email = "alice.renamed@example.com"  # same sub, different email
    assert sign_in(client, idp).headers["location"] == f"{FRONTEND}/"
    assert client.get("/api/v1/auth/me").json()["id"] == first_id
    assert count_users(db) == 1
    # a different sub with the first user's email must not take over the existing identity
    idp.sub, idp.email = "g-sub-other", "alice@example.com"
    sign_in(client, idp)
    assert len(db.scalars(select(AuthAccount)).all()) == 2


def test_user_from_provider_requires_verified_email_for_unknown_identity(db):
    with pytest.raises(oauth.OAuthError) as info:
        user_from_provider(db, "github", "77", "new@example.com", "New")
    assert info.value.public == "oauth_email_unverified"
    assert count_users(db) == 0
    user = user_from_provider(db, "github", "77", "new@example.com", "New", email_verified=True)
    assert user.email_verified is True and user.password_hash is None
    # known identity resolves by (provider, sub) even with unverified email input
    assert user_from_provider(db, "github", "77", "other@example.com", "New").id == user.id


# -------------------------------------------------------------------- redirects


@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.example/",
        "http://evil.example",
        "//evil.example",
        "///evil.example",
        "/\\evil.example",
        "\\\\evil.example",
        "/%2F%2Fevil.example",
        "/%5Cevil.example",
        "javascript:alert(1)",
        "evil.example",
        "http:evil.example",
        "/ok\r\nSet-Cookie: pwn=1",
        "/ok\x00",
        "/" + "a" * 600,
    ],
)
def test_open_redirect_attempts_land_on_root(client, idp, bad):
    done = sign_in(client, idp, next_=bad)
    assert done.headers["location"] == f"{FRONTEND}/"


def test_valid_relative_next_is_preserved(client, idp):
    done = sign_in(client, idp, next_="/analyses/abc?tab=risk")
    assert done.headers["location"] == f"{FRONTEND}/analyses/abc?tab=risk"


def test_sanitize_next_unit():
    assert oauth.sanitize_next(None) == "/"
    assert oauth.sanitize_next("/a/b?c=d#e") == "/a/b?c=d#e"
    assert oauth.sanitize_next("//x") == "/"
    assert oauth.sanitize_next("/x\\y") == "/"


@pytest.mark.parametrize(
    "uri",
    [
        "http://evil.example/api/v1/auth/oauth/google/callback",  # http, not local
        "https://app.example/api/v1/auth/oauth/google/callback?x=1",
        "https://app.example/api/v1/auth/oauth/google/callback#f",
        "https://app.example/other",
        "https://user:pw@app.example/api/v1/auth/oauth/google/callback",
        "https://app.example/api/v1/auth/oauth/github/callback",
        "ftp://app.example/api/v1/auth/oauth/google/callback",
    ],
)
def test_redirect_uri_allow_list(uri):
    with pytest.raises(oauth.OAuthError):
        oauth.validate_redirect_uri("google", uri, production=False)


def test_redirect_uri_local_http_only_outside_production():
    ok = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    assert oauth.validate_redirect_uri("google", ok, production=False) == ok
    with pytest.raises(oauth.OAuthError):
        oauth.validate_redirect_uri("google", ok, production=True)
    https = "https://app.example/api/v1/auth/oauth/google/callback"
    assert oauth.validate_redirect_uri("google", https, production=True) == https


def test_misconfigured_redirect_uri_blocks_sign_in(client, idp, monkeypatch):
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://app.example/elsewhere")
    get_settings.cache_clear()
    assert client.get("/api/v1/auth/oauth/google").status_code == 503


def test_not_configured_and_unknown_provider(client, idp, monkeypatch):
    assert client.get("/api/v1/auth/oauth/gitlab").status_code == 404
    assert client.get(CB.format("gitlab"), params={"code": "a", "state": "b"}).status_code == 404
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    get_settings.cache_clear()
    assert client.get("/api/v1/auth/oauth/google").status_code == 503


def test_production_requires_https_redirect_uris():
    with pytest.raises(ValueError, match="https"):
        Settings(
            _env_file=None,
            runtime_env="production",
            session_secret=secrets.token_hex(24),
            email_delivery_mode="smtp",
            google_redirect_uri=GOOGLE_CB,
        )


# ----------------------------------------------------------------------- GitHub


def test_github_happy_path_uses_pkce_and_verified_primary_email(client, idp, db):
    idp.github_profile_email = "spoof@victim.example"  # public profile email is ignored
    idp.github_emails = [
        {"email": "unverified@example.com", "primary": False, "verified": False},
        {"email": "Alice@Example.com", "primary": True, "verified": True},
        {"email": "other@example.com", "primary": False, "verified": True},
    ]
    start, code, state = begin(client, idp, "github")
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and "nonce" not in query
    assert query["scope"] == ["read:user user:email"]
    done = finish(client, "github", code, state)
    assert done.headers["location"] == f"{FRONTEND}/"
    assert "code_verifier" in idp.token_requests[0]
    assert client.get("/api/v1/auth/me").json()["email"] == "alice@example.com"
    account = db.scalars(select(AuthAccount)).one()
    assert (account.provider, account.provider_account_id) == ("github", "4242")


@pytest.mark.parametrize(
    "emails",
    [
        [{"email": "a@example.com", "primary": True, "verified": False}],
        [{"email": "a@example.com", "primary": False, "verified": True}],
        [],
        {"message": "Not Found"},
    ],
)
def test_github_without_primary_verified_email_is_refused(client, idp, db, emails):
    idp.github_profile_email = "alice@example.com"
    idp.github_emails = emails
    assert error_of(sign_in(client, idp, "github")) in {"oauth", "oauth_email_unverified"}
    assert count_users(db) == 0


def test_github_pkce_mismatch_and_token_error(client, idp):
    idp.challenge_override = _b64(hashlib.sha256(b"x").digest())
    assert error_of(sign_in(client, idp, "github")) == "oauth"
    idp.challenge_override = None
    idp.token_mode = "error200"
    assert error_of(sign_in(client, idp, "github")) == "oauth"


def test_github_unverified_local_account_not_linked(client, idp, db):
    db.add(AuthUser(name="A", email="alice@example.com", email_verified=False))
    db.commit()
    assert error_of(sign_in(client, idp, "github")) == "oauth_link_refused"


# ---------------------------------------------------------------- logging, limits


def test_logs_never_contain_codes_tokens_secrets_or_verifier(client, idp, db, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    start, code, state = begin(client, idp)
    verifier = db.scalars(select(AuthOAuthFlow)).one().code_verifier
    finish(client, "google", code, state)
    idp.claims = {"aud": "nope"}
    start, code2, state2 = begin(client, idp)
    finish(client, "google", code2, state2)
    idp.token_mode = "http400"
    start, code3, state3 = begin(client, idp)
    finish(client, "google", code3, state3)
    # The TestClient's own httpx logger echoes request URLs; only the API's records matter here.
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app."))
    assert "outcome=failure" in text and "outcome=success" in text
    for secret in (code, code2, code3, state, state2, idp.client_secret, idp.access_token, verifier):
        assert secret not in text
    assert "eyJ" not in text


def test_callback_is_in_the_auth_rate_limit_bucket():
    assert classify_request("GET", "/api/v1/auth/oauth/google/callback") == "auth"
    assert classify_request("GET", "/api/v1/auth/oauth/github") == "auth"


def test_callback_is_rate_limited(make_client, idp, monkeypatch):
    monkeypatch.setenv("RADIUS_RATE_LIMIT_AUTH", "5/60")
    client = make_client()
    statuses = [
        client.get(CB.format("google"), params={"code": "x", "state": "y"}).status_code
        for _ in range(30)
    ]
    assert statuses[:5] == [307] * 5
    assert 429 in statuses


# ------------------------------------------------------- password sign-in intact


def test_password_sign_in_is_unaffected(client, idp, db):
    signup = client.post(
        "/api/v1/auth/signup",
        json={"name": "Pat Password", "email": "pat@example.com", "password": "Passw0rdLong1"},
    )
    assert signup.status_code == 201
    client.cookies.clear()
    bad = client.post(
        "/api/v1/auth/login", json={"email": "pat@example.com", "password": "Wrong-pass1"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/api/v1/auth/login", json={"email": "pat@example.com", "password": "Passw0rdLong1"}
    )
    assert good.status_code == 200
    assert client.get("/api/v1/auth/me").json()["email"] == "pat@example.com"
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert idp.calls == []  # no provider traffic at all
