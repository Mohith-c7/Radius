"""Idempotency helpers for mutating API requests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import Request
from radius_shared.database import models as db_models
from radius_shared.errors import ConflictError, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Stored response for a previously completed idempotent request."""

    id: UUID
    organization_id: UUID
    key: str
    scope: str
    request_hash: str
    status_code: int
    response_body: dict


class IdempotencyStore(Protocol):
    """Persistence contract for idempotent request records."""

    def get(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
    ) -> IdempotencyRecord | None:
        """Return a stored idempotency record."""

    def save(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
        request_hash: str,
        status_code: int,
        response_body: dict,
    ) -> IdempotencyRecord:
        """Persist an idempotency response."""


class InMemoryIdempotencyStore:
    """Process-local idempotency store for tests and local development."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    def get(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
    ) -> IdempotencyRecord | None:
        return self._records.get((organization_id, key, scope))

    def save(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
        request_hash: str,
        status_code: int,
        response_body: dict,
    ) -> IdempotencyRecord:
        record = IdempotencyRecord(
            id=uuid4(),
            organization_id=organization_id,
            key=key,
            scope=scope,
            request_hash=request_hash,
            status_code=status_code,
            response_body=response_body,
        )
        self._records[(organization_id, key, scope)] = record
        return record


class SqlAlchemyIdempotencyStore:
    """SQLAlchemy idempotency store."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
    ) -> IdempotencyRecord | None:
        row = self._session.scalar(
            select(db_models.IdempotencyKey).where(
                db_models.IdempotencyKey.organization_id == organization_id,
                db_models.IdempotencyKey.key == key,
                db_models.IdempotencyKey.scope == scope,
            )
        )
        return self._to_record(row)

    def save(
        self,
        organization_id: UUID,
        key: str,
        scope: str,
        request_hash: str,
        status_code: int,
        response_body: dict,
    ) -> IdempotencyRecord:
        row = db_models.IdempotencyKey(
            organization_id=organization_id,
            key=key,
            scope=scope,
            request_hash=request_hash,
            status_code=status_code,
            response_body=response_body,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        record = self._to_record(row)
        if record is None:
            msg = "Idempotency record could not be saved."
            raise ValidationError(msg)
        return record

    @staticmethod
    def _to_record(row: db_models.IdempotencyKey | None) -> IdempotencyRecord | None:
        if row is None:
            return None
        return IdempotencyRecord(
            id=row.id,
            organization_id=row.organization_id,
            key=row.key,
            scope=row.scope,
            request_hash=row.request_hash,
            status_code=row.status_code,
            response_body=row.response_body,
        )


async def request_hash(request: Request) -> str:
    """Return a stable hash for the raw request body."""

    body = await request.body()
    return hashlib.sha256(body).hexdigest()


def replay_or_validate(
    store: IdempotencyStore,
    organization_id: UUID,
    key: str | None,
    scope: str,
    body_hash: str,
) -> IdempotencyRecord | None:
    """Return an existing record or validate that a new request can run."""

    if key is None:
        return None
    existing = store.get(organization_id, key, scope)
    if existing is None:
        return None
    if existing.request_hash != body_hash:
        msg = "Idempotency-Key was reused with a different request body."
        raise ConflictError(msg)
    return existing
