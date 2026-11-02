"""Request and response models for ``/api/v1/api-keys``."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """Create a key bound to the caller's organization."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyRotateRequest(BaseModel):
    """Rotation options; the old key stays valid for the overlap window."""

    model_config = ConfigDict(extra="forbid")

    overlap_seconds: int = Field(default=24 * 3600, ge=0)


class ApiKeyView(BaseModel):
    """A key as listed: identifiable by prefix, never the secret or its hash."""

    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_by: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    rotated_from_id: UUID | None

    @classmethod
    def from_row(cls, row) -> "ApiKeyView":
        return cls(
            id=row.id,
            name=row.name,
            prefix=f"rdk_{row.prefix}",
            scopes=list(row.scopes),
            created_by=row.created_by,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            rotated_from_id=row.rotated_from_id,
        )


class ApiKeyCreated(BaseModel):
    """Returned once on create and rotate; ``token`` is not retrievable later."""

    key: ApiKeyView
    token: str
    replaced: ApiKeyView | None = None


class ApiKeyAuditView(BaseModel):
    """One audit entry."""

    id: UUID
    api_key_id: UUID
    action: str
    actor: str
    detail: dict
    created_at: datetime
