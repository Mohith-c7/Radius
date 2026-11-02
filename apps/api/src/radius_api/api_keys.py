"""Managed API key lifecycle: create, list, rotate, revoke, authenticate (PRD-12)."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import Request
from radius_shared.database.api_keys import ApiKey, ApiKeyAuditEvent
from radius_shared.errors import NotFoundError, ValidationError
from radius_shared.logging import get_logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radius_api.token_fingerprint import (
    fingerprints_match,
    new_token,
    token_fingerprint,
    token_prefix,
)

_LOG = get_logger("radius.api.keys")

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_CI_UPLOAD = "ci-upload"
SCOPE_ADMIN = "admin"
ALL_SCOPES = frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_CI_UPLOAD, SCOPE_ADMIN})

#: A granted scope also satisfies these scopes (least privilege otherwise).
_IMPLIES = {
    SCOPE_ADMIN: ALL_SCOPES,
    SCOPE_WRITE: frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_CI_UPLOAD}),
    SCOPE_READ: frozenset({SCOPE_READ}),
    SCOPE_CI_UPLOAD: frozenset({SCOPE_CI_UPLOAD}),
}
MAX_OVERLAP_SECONDS = 30 * 24 * 3600
DEFAULT_OVERLAP_SECONDS = 24 * 3600
DEV_PEPPER = "radius-insecure-dev-pepper-not-for-production"
_DUMMY_HASH = "0" * 64


def effective_scopes(granted: frozenset[str] | set[str] | list[str]) -> frozenset[str]:
    """Expand granted scopes with the scopes they imply."""

    out: set[str] = set()
    for scope in granted:
        out |= _IMPLIES.get(scope, frozenset())
    return frozenset(out)


def aware(value: datetime | None) -> datetime | None:
    """Treat naive datetimes (SQLite) as UTC."""

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ApiKeyStore(Protocol):
    """Persistence port. Every method is scoped to one organization."""

    def add(self, key: ApiKey) -> None: ...
    def get(self, organization_id: UUID, key_id: UUID) -> ApiKey | None: ...
    def find_by_prefix(self, organization_id: UUID, prefix: str) -> ApiKey | None: ...
    def list(self, organization_id: UUID) -> list[ApiKey]: ...
    def add_audit(self, event: ApiKeyAuditEvent) -> None: ...
    def list_audit(self, organization_id: UUID) -> list[ApiKeyAuditEvent]: ...
    def flush(self) -> None: ...


class InMemoryApiKeyStore:
    """Process-local store used when ``STORAGE_BACKEND=memory``."""

    def __init__(self) -> None:
        self._keys: dict[UUID, ApiKey] = {}
        self._audit: list[ApiKeyAuditEvent] = []

    def add(self, key: ApiKey) -> None:
        self._keys[key.id] = key

    def get(self, organization_id: UUID, key_id: UUID) -> ApiKey | None:
        key = self._keys.get(key_id)
        return key if key and key.organization_id == organization_id else None

    def find_by_prefix(self, organization_id: UUID, prefix: str) -> ApiKey | None:
        return next(
            (
                k
                for k in self._keys.values()
                if k.organization_id == organization_id and k.prefix == prefix
            ),
            None,
        )

    def list(self, organization_id: UUID) -> list[ApiKey]:
        rows = [k for k in self._keys.values() if k.organization_id == organization_id]
        return sorted(rows, key=lambda k: k.created_at)

    def add_audit(self, event: ApiKeyAuditEvent) -> None:
        self._audit.append(event)

    def list_audit(self, organization_id: UUID) -> list[ApiKeyAuditEvent]:
        return [e for e in self._audit if e.organization_id == organization_id]

    def flush(self) -> None:
        """Nothing to flush in memory."""


class SqlAlchemyApiKeyStore:
    """SQL store bound to one session (the caller commits)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, key: ApiKey) -> None:
        self._session.add(key)

    def get(self, organization_id: UUID, key_id: UUID) -> ApiKey | None:
        return self._session.scalars(
            select(ApiKey).where(
                ApiKey.organization_id == organization_id, ApiKey.id == key_id
            )
        ).first()

    def find_by_prefix(self, organization_id: UUID, prefix: str) -> ApiKey | None:
        return self._session.scalars(
            select(ApiKey).where(
                ApiKey.organization_id == organization_id, ApiKey.prefix == prefix
            )
        ).first()

    def list(self, organization_id: UUID) -> list[ApiKey]:
        return list(
            self._session.scalars(
                select(ApiKey)
                .where(ApiKey.organization_id == organization_id)
                .order_by(ApiKey.created_at)
            )
        )

    def add_audit(self, event: ApiKeyAuditEvent) -> None:
        self._session.add(event)

    def list_audit(self, organization_id: UUID) -> list[ApiKeyAuditEvent]:
        return list(
            self._session.scalars(
                select(ApiKeyAuditEvent)
                .where(ApiKeyAuditEvent.organization_id == organization_id)
                .order_by(ApiKeyAuditEvent.created_at)
            )
        )

    def flush(self) -> None:
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            msg = "Organization was not found."
            raise NotFoundError(msg) from exc


class ApiKeyService:
    """Business rules for managed keys. Secrets leave only from create/rotate."""

    def __init__(
        self,
        store: ApiKeyStore,
        *,
        pepper: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        last_used_interval_seconds: int = 300,
    ) -> None:
        self._store = store
        self._pepper = pepper
        self._clock = clock
        self._last_used_interval = timedelta(seconds=last_used_interval_seconds)

    @property
    def enabled(self) -> bool:
        """Managed keys need a pepper; without one they are disabled."""

        return bool(self._pepper)

    def _require_enabled(self) -> None:
        if not self.enabled:
            msg = "Managed API keys are disabled: set RADIUS_API_KEY_PEPPER."
            raise ValidationError(msg)

    def create(
        self,
        organization_id: UUID,
        *,
        name: str,
        scopes: list[str],
        actor: str,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKey, str]:
        """Create a key; returns the record and the one-time plaintext token."""

        self._require_enabled()
        clean = sorted(set(scopes))
        if not clean or not set(clean) <= ALL_SCOPES:
            msg = f"scopes must be a non-empty subset of {sorted(ALL_SCOPES)}."
            raise ValidationError(msg)
        expires_at = aware(expires_at)
        if expires_at is not None and expires_at <= self._clock():
            msg = "expires_at must be in the future."
            raise ValidationError(msg)
        key, token = self._issue(organization_id, name, clean, actor, expires_at, None)
        self._audit(key, "created", actor, {"scopes": clean, "name": name})
        return key, token

    def _issue(
        self,
        organization_id: UUID,
        name: str,
        scopes: list[str],
        actor: str,
        expires_at: datetime | None,
        rotated_from: UUID | None,
    ) -> tuple[ApiKey, str]:
        for _ in range(8):  # prefix collisions are astronomically rare; retry anyway
            token, prefix = new_token()
            if self._store.find_by_prefix(organization_id, prefix) is None:
                break
        else:  # pragma: no cover - 8 consecutive 32-bit collisions
            msg = "Could not allocate a unique key prefix."
            raise RuntimeError(msg)
        key = ApiKey(
            id=uuid4(),
            organization_id=organization_id,
            name=name,
            prefix=prefix,
            key_hash=token_fingerprint(token, self._pepper),
            scopes=list(scopes),
            created_by=actor,
            created_at=self._clock(),
            expires_at=expires_at,
            rotated_from_id=rotated_from,
        )
        self._store.add(key)
        self._store.flush()
        return key, token

    def list(self, organization_id: UUID) -> list[ApiKey]:
        """List the organization's keys (no secrets exist to return)."""

        return self._store.list(organization_id)

    def audit_events(self, organization_id: UUID) -> list[ApiKeyAuditEvent]:
        """List the organization's key audit events."""

        return self._store.list_audit(organization_id)

    def _owned(self, organization_id: UUID, key_id: UUID) -> ApiKey:
        key = self._store.get(organization_id, key_id)
        if key is None:
            msg = "API key was not found."
            raise NotFoundError(msg)
        return key

    def rotate(
        self,
        organization_id: UUID,
        key_id: UUID,
        *,
        actor: str,
        overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
    ) -> tuple[ApiKey, str, ApiKey]:
        """Issue a replacement; the old key keeps working for ``overlap_seconds``."""

        self._require_enabled()
        if not 0 <= overlap_seconds <= MAX_OVERLAP_SECONDS:
            msg = f"overlap_seconds must be between 0 and {MAX_OVERLAP_SECONDS}."
            raise ValidationError(msg)
        old = self._owned(organization_id, key_id)
        now = self._clock()
        if not self._is_active(old, now):
            msg = "Only an active key can be rotated."
            raise ValidationError(msg)
        cutoff = now + timedelta(seconds=overlap_seconds)
        old_expiry = aware(old.expires_at)
        old.expires_at = min(cutoff, old_expiry) if old_expiry else cutoff
        new, token = self._issue(
            organization_id, old.name, list(old.scopes), actor, old_expiry, old.id
        )
        self._audit(
            new,
            "rotated",
            actor,
            {"replaces": str(old.id), "old_expires_at": old.expires_at.isoformat()},
        )
        return new, token, old

    def revoke(self, organization_id: UUID, key_id: UUID, *, actor: str) -> ApiKey:
        """Revoke immediately. Idempotent."""

        key = self._owned(organization_id, key_id)
        if key.revoked_at is None:
            key.revoked_at = self._clock()
            key.revoked_by = actor
            self._audit(key, "revoked", actor, {})
        return key

    @staticmethod
    def _is_active(key: ApiKey, now: datetime) -> bool:
        expires = aware(key.expires_at)
        return key.revoked_at is None and (expires is None or expires > now)

    def authenticate(self, organization_id: UUID, token: str) -> ApiKey | None:
        """Return the active key matching ``token`` for the org, else ``None``.

        The fingerprint is always computed and compared (against a dummy when no
        row matched) so unknown, revoked and expired keys take the same path.
        """

        prefix = token_prefix(token)
        key = (
            self._store.find_by_prefix(organization_id, prefix)
            if prefix and self.enabled
            else None
        )
        digest = token_fingerprint(token, self._pepper or DEV_PEPPER)
        matched = fingerprints_match(digest, key.key_hash if key else _DUMMY_HASH)
        now = self._clock()
        if key is None or not matched or not self._is_active(key, now):
            return None
        last = aware(key.last_used_at)
        if last is None or now - last >= self._last_used_interval:
            key.last_used_at = now  # rate-limited write
        return key

    def _audit(self, key: ApiKey, action: str, actor: str, detail: dict) -> None:
        self._store.add_audit(
            ApiKeyAuditEvent(
                id=uuid4(),
                organization_id=key.organization_id,
                api_key_id=key.id,
                action=action,
                actor=actor,
                detail=detail,
                created_at=self._clock(),
            )
        )
        _LOG.info("api key %s: prefix=%s actor=%s", action, key.prefix, actor)


def build_service(request: Request, store: ApiKeyStore) -> ApiKeyService:
    """Build the service from app settings."""

    settings = request.app.state.settings
    pepper = getattr(settings, "api_key_pepper", "")
    if not pepper and getattr(settings, "insecure_dev_mode", False):
        pepper = DEV_PEPPER
    return ApiKeyService(
        store,
        pepper=pepper,
        clock=request.app.state.container.clock,
        last_used_interval_seconds=getattr(
            settings, "api_key_last_used_interval_seconds", 300
        ),
    )


@contextmanager
def open_service(request: Request) -> Iterator[ApiKeyService]:
    """Yield a service in its own short transaction (commit on success)."""

    container = request.app.state.container
    if container.session_factory is None:
        yield build_service(request, container.api_key_store)
        return
    session = container.session_factory()
    try:
        yield build_service(request, SqlAlchemyApiKeyStore(session))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
