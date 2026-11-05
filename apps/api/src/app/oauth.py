"""OAuth 2.0 / OpenID Connect sign-in primitives (Google = OIDC, GitHub = plain OAuth 2.0).

Security properties implemented here (see docs/security/SSO_DESIGN.md):

* authorization code flow with PKCE (S256); the verifier never leaves the server;
* ``state`` is random, stored hashed server-side, bound to the browser by a flow cookie,
  expires after ten minutes and is single use (the row is deleted before anything else);
* OIDC ``nonce`` is checked against the ID token;
* ID-token validation: RS256 only (``none``/HS*/unknown algs refused), key chosen by ``kid``
  from the provider's JWKS (cached, refetched at most once a minute on an unknown ``kid``),
  ``iss``, ``aud`` (+ ``azp`` when several audiences), ``exp``, ``iat``, ``sub``, ``nonce``;
* ``email_verified`` must be exactly ``true`` before an email is used for anything;
* the redirect URI is never taken from the request and is checked against a strict shape;
* ``next`` is accepted only as a same-origin relative path.

Failures raise :class:`OAuthError` with a short machine code; callers log the code and the
exception class, never provider responses, codes, tokens or secrets.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import AuthOAuthFlow

FLOW_COOKIE = "radius_oauth_flow"
FLOW_COOKIE_PATH = "/api/v1/auth/oauth"
FLOW_TTL = timedelta(minutes=10)
CLOCK_SKEW_SECONDS = 60
JWKS_TTL_SECONDS = 3600
JWKS_MIN_REFETCH_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1_000_000
ALLOWED_ID_TOKEN_ALGS = ("RS256",)
MAX_NEXT_LENGTH = 512

# Error codes that are safe to show on the login page (``/login?error=<code>``).
PUBLIC_ERROR_CODES = frozenset(
    {"oauth", "oauth_denied", "oauth_email_unverified", "oauth_link_refused"}
)


class OAuthError(Exception):
    """A sign-in failure. ``public`` is the code placed on the login redirect."""

    def __init__(self, code: str, public: str = "oauth") -> None:
        super().__init__(code)
        self.code = code
        self.public = public if public in PUBLIC_ERROR_CODES else "oauth"


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    name: str
    authorize_url: str
    token_url: str
    scope: str
    oidc: bool
    pkce: bool
    jwks_url: str | None = None
    issuers: tuple[str, ...] = ()
    profile_url: str | None = None  # GitHub: GET /user
    emails_url: str | None = None  # GitHub: GET /user/emails


PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile",
        oidc=True,
        pkce=True,
        jwks_url="https://www.googleapis.com/oauth2/v3/certs",
        issuers=("https://accounts.google.com", "accounts.google.com"),
    ),
    "github": OAuthProvider(
        name="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scope="read:user user:email",
        oidc=False,
        pkce=True,  # GitHub documents S256 PKCE for OAuth Apps; not verifiable offline.
        profile_url="https://api.github.com/user",
        emails_url="https://api.github.com/user/emails",
    ),
}


def make_http_client() -> httpx.AsyncClient:
    """HTTP client for provider calls. Tests replace this to serve a local stub IdP."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False)


# --------------------------------------------------------------------------- helpers


#: Fixed, public, per-purpose salt: the digest only has to be deterministic (it is a lookup key for a
#: random, single-use, 10-minute token), not secret. PBKDF2 is used because static analysis (CodeQL
#: py/weak-sensitive-data-hashing) rejects a bare SHA-256 of a value named like a secret.
_TOKEN_DIGEST_SALT = b"radius-oauth-flow-token-v1"
_TOKEN_DIGEST_ROUNDS = 10_000


def _token_digest(value: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", value.encode(), _TOKEN_DIGEST_SALT, _TOKEN_DIGEST_ROUNDS).hex()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sanitize_next(value: str | None) -> str:
    """Return ``value`` only if it is a same-origin relative path, else ``/``.

    Rejects scheme-relative (``//host``), backslash tricks, control characters, absolute
    URLs and anything with a scheme or authority, also after one round of percent-decoding.
    """
    if not value or len(value) > MAX_NEXT_LENGTH:
        return "/"
    for item in (value, unquote(value)):
        if not item.startswith("/") or item.startswith("//"):
            return "/"
        if "\\" in item or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in item):
            return "/"
        parts = urlsplit(item)
        if parts.scheme or parts.netloc:
            return "/"
    return value


def validate_redirect_uri(provider: str, redirect_uri: str, *, production: bool) -> str:
    """Strict shape check for the configured redirect URI (it is never read from a request)."""
    parts = urlsplit(redirect_uri)
    expected_path = f"/api/v1/auth/oauth/{provider}/callback"
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    ok = (
        parts.scheme in {"https", "http"}
        and bool(parts.hostname)
        and (parts.scheme == "https" or (local and not production))
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and parts.path == expected_path
    )
    if not ok:
        raise OAuthError("redirect_uri_invalid")
    return redirect_uri


# ------------------------------------------------------------------- flow state (DB)


def start_flow(db: Session, provider: OAuthProvider, next_path: str) -> tuple[str, str, str, str]:
    """Create a flow row. Returns ``(flow_id, state, nonce, code_verifier)``."""
    now = datetime.now(UTC)
    db.execute(delete(AuthOAuthFlow).where(AuthOAuthFlow.expires_at < now))
    flow_id = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636's 43..128
    db.add(
        AuthOAuthFlow(
            flow_hash=_token_digest(flow_id),
            state_hash=_token_digest(state),
            provider=provider.name,
            nonce=nonce,
            code_verifier=verifier,
            next_path=sanitize_next(next_path),
            expires_at=now + FLOW_TTL,
        )
    )
    db.commit()
    return flow_id, state, nonce, verifier


@dataclass(frozen=True, slots=True)
class ConsumedFlow:
    nonce: str
    code_verifier: str
    next_path: str


def consume_flow(
    db: Session, provider: str, flow_id: str | None, state: str | None
) -> ConsumedFlow:
    """Atomically delete the flow for this browser and return it, or raise.

    The row is removed before ``state``/provider/expiry are judged, so a failed attempt can
    never be retried with the same flow.
    """
    if not flow_id or not state:
        raise OAuthError("state_missing")
    row = db.scalar(select(AuthOAuthFlow).where(AuthOAuthFlow.flow_hash == _token_digest(flow_id)))
    if row is None:
        raise OAuthError("flow_unknown")
    state_hash, flow_provider, expires_at = row.state_hash, row.provider, row.expires_at
    consumed = ConsumedFlow(row.nonce, row.code_verifier, row.next_path)
    deleted = db.execute(delete(AuthOAuthFlow).where(AuthOAuthFlow.id == row.id)).rowcount
    db.commit()
    if deleted != 1:
        raise OAuthError("flow_replayed")
    if not secrets.compare_digest(state_hash, _token_digest(state)):
        raise OAuthError("state_mismatch")
    if flow_provider != provider:
        raise OAuthError("provider_mismatch")
    if _aware(expires_at) < datetime.now(UTC):
        raise OAuthError("flow_expired")
    return consumed


# --------------------------------------------------------------------------- JWKS


class JwksCache:
    """Per-URL JWKS cache: ``kid`` -> RSA public key.

    TTL one hour. A miss (unknown ``kid`` or stale cache) triggers a refetch, but never more
    than once per minute per URL, so a flood of forged ``kid`` values cannot hammer the
    provider. Key rotation is picked up on the first token signed by the new key.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: dict[str, float] = {}
        self._attempted_at: dict[str, float] = {}
        self._lock: asyncio.Lock | None = None

    def reset(self) -> None:
        self._keys.clear()
        self._fetched_at.clear()
        self._attempted_at.clear()
        self._lock = None

    async def get_key(self, client: httpx.AsyncClient, url: str, kid: str) -> Any:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = self._clock()
            fresh = url in self._fetched_at and now - self._fetched_at[url] < JWKS_TTL_SECONDS
            key = self._keys.get(url, {}).get(kid) if fresh else None
            if key is not None:
                return key
            last = self._attempted_at.get(url)
            if last is not None and now - last < JWKS_MIN_REFETCH_SECONDS:
                raise OAuthError("jwks_kid_unknown")
            self._attempted_at[url] = now
            keys = await self._fetch(client, url)
            self._keys[url] = keys
            self._fetched_at[url] = now
            key = keys.get(kid)
            if key is None:
                raise OAuthError("jwks_kid_unknown")
            return key

    @staticmethod
    async def _fetch(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        try:
            response = await client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise OAuthError("jwks_unavailable") from exc
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
            raise OAuthError("jwks_unavailable")
        try:
            raw_keys = response.json()["keys"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OAuthError("jwks_invalid") from exc
        keys: dict[str, Any] = {}
        for jwk in raw_keys if isinstance(raw_keys, list) else []:
            if not isinstance(jwk, dict) or jwk.get("kty") != "RSA" or not jwk.get("kid"):
                continue
            if jwk.get("use", "sig") != "sig" or jwk.get("alg", "RS256") != "RS256":
                continue
            try:
                keys[str(jwk["kid"])] = RSAAlgorithm.from_jwk(json.dumps(jwk))
            except (jwt.PyJWTError, ValueError, TypeError):
                continue
        return keys


JWKS_CACHE = JwksCache()


# ----------------------------------------------------------------- ID token (OIDC)


async def validate_id_token(
    client: httpx.AsyncClient,
    provider: OAuthProvider,
    id_token: str,
    *,
    client_id: str,
    nonce: str,
) -> dict[str, Any]:
    """Verify an ID token and return its claims, or raise :class:`OAuthError`."""
    if not provider.jwks_url:
        raise OAuthError("provider_not_oidc")
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OAuthError("id_token_malformed") from exc
    if header.get("alg") not in ALLOWED_ID_TOKEN_ALGS:
        raise OAuthError("id_token_alg")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise OAuthError("id_token_kid")
    key = await JWKS_CACHE.get_key(client, provider.jwks_url, kid)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=list(ALLOWED_ID_TOKEN_ALGS),
            audience=client_id,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=CLOCK_SKEW_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthError("id_token_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise OAuthError("id_token_aud") from exc
    except jwt.PyJWTError as exc:
        raise OAuthError("id_token_invalid") from exc
    if claims.get("iss") not in provider.issuers:
        raise OAuthError("id_token_iss")
    audience = claims["aud"]
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id:
        raise OAuthError("id_token_azp")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise OAuthError("id_token_sub")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not secrets.compare_digest(
        token_nonce.encode(), nonce.encode()
    ):
        raise OAuthError("id_token_nonce")
    return claims


# ------------------------------------------------------------- token + identity fetch


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider: str
    subject: str
    email: str
    name: str
    #: GitHub ``login`` (B-07); ``None`` for providers without one.
    login: str | None = None


def _json_object(response: httpx.Response, code: str) -> dict[str, Any]:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise OAuthError(code)
    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthError(code) from exc
    if not isinstance(body, dict):
        raise OAuthError(code)
    return body


async def exchange_code(
    client: httpx.AsyncClient,
    provider: OAuthProvider,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if provider.pkce:
        data["code_verifier"] = code_verifier
    try:
        response = await client.post(
            provider.token_url, data=data, headers={"Accept": "application/json"}
        )
    except httpx.HTTPError as exc:
        raise OAuthError("token_unavailable") from exc
    if response.status_code != 200:
        raise OAuthError("token_http_error")
    body = _json_object(response, "token_invalid")
    if "error" in body:  # GitHub reports failures with HTTP 200 and an ``error`` field
        raise OAuthError("token_error")
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError("token_invalid")
    token_type = body.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise OAuthError("token_invalid")
    return body


async def _github_identity(
    client: httpx.AsyncClient, provider: OAuthProvider, access_token: str
) -> ProviderIdentity:
    if not provider.profile_url or not provider.emails_url:
        raise OAuthError("provider_not_configured")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        profile_response = await client.get(provider.profile_url, headers=headers)
        emails_response = await client.get(provider.emails_url, headers=headers)
    except httpx.HTTPError as exc:
        raise OAuthError("profile_unavailable") from exc
    if profile_response.status_code != 200 or emails_response.status_code != 200:
        raise OAuthError("profile_http_error")
    profile = _json_object(profile_response, "profile_invalid")
    github_id = profile.get("id")
    if not isinstance(github_id, int) or isinstance(github_id, bool) or github_id <= 0:
        raise OAuthError("profile_invalid")
    try:
        emails = emails_response.json()
    except ValueError as exc:
        raise OAuthError("profile_invalid") from exc
    if not isinstance(emails, list):
        raise OAuthError("profile_invalid")
    # Only /user/emails is trusted; the public profile ``email`` is user-controlled text.
    primary_verified = [
        item["email"]
        for item in emails
        if isinstance(item, dict)
        and item.get("primary") is True
        and item.get("verified") is True
        and isinstance(item.get("email"), str)
        and item["email"].strip()
    ]
    if not primary_verified:
        raise OAuthError("email_unverified", public="oauth_email_unverified")
    email = primary_verified[0].strip().lower()
    name = profile.get("name") or profile.get("login") or email
    raw_login = profile.get("login")
    login = (
        raw_login
        if isinstance(raw_login, str) and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", raw_login)
        else None
    )
    return ProviderIdentity("github", str(github_id), email, str(name)[:120], login)


async def fetch_identity(
    client: httpx.AsyncClient,
    provider: OAuthProvider,
    token_body: dict[str, Any],
    *,
    client_id: str,
    nonce: str,
) -> ProviderIdentity:
    if not provider.oidc:
        return await _github_identity(client, provider, token_body["access_token"])
    id_token = token_body.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise OAuthError("id_token_missing")
    claims = await validate_id_token(client, provider, id_token, client_id=client_id, nonce=nonce)
    email = claims.get("email")
    if claims.get("email_verified") is not True:
        raise OAuthError("email_unverified", public="oauth_email_unverified")
    if not isinstance(email, str) or not email.strip():
        raise OAuthError("email_missing", public="oauth_email_unverified")
    email = email.strip().lower()
    raw_name = claims.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name.strip() else email
    return ProviderIdentity(provider.name, claims["sub"], email, name[:120])
