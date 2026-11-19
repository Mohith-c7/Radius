"""Operator bootstrap: create the organization row and, optionally, the first managed key.

Run it once after ``alembic upgrade head`` (inside the API container it reuses the
API's own environment)::

    docker compose exec api python -m radius_api.bootstrap \\
        --organization-id <uuid> --name "Acme" --create-admin-key bootstrap-admin

* The organization row is created when absent; an existing row is never changed.
* ``--create-admin-key`` issues a managed ``rdk_`` key through ``ApiKeyService`` (same
  fingerprint, pepper and audit path as ``POST /api/v1/api-keys``, actor ``bootstrap-cli``).
  It needs ``RADIUS_API_KEY_PEPPER``. An active key with the same name is not duplicated.
* Status messages go to stderr; stdout carries only the new key's token, printed once.

Exit codes: 0 success, 1 failure (database unreachable or not migrated), 2 usage or
configuration error.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError as SettingsError
from radius_shared.database.api_keys import ApiKey, ApiKeyAuditEvent
from radius_shared.database.models import Organization
from radius_shared.database.session import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from radius_shared.errors import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from radius_api.api_keys import SCOPE_ADMIN, ApiKeyService, SqlAlchemyApiKeyStore, aware
from radius_api.config import ApiSettings

ACTOR = "bootstrap-cli"
EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
ORG_ID_ENV = ("GITHUB_DEFAULT_ORGANIZATION_ID", "NEXT_PUBLIC_RADIUS_ORGANIZATION_ID")


class UsageError(Exception):
    """Bad arguments or configuration (exit code 2)."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m radius_api.bootstrap",
        description="Create the organization row (idempotent) and optionally its first managed API key.",
    )
    parser.add_argument(
        "--organization-id",
        help="Organization UUID. Default: GITHUB_DEFAULT_ORGANIZATION_ID, then "
        "NEXT_PUBLIC_RADIUS_ORGANIZATION_ID.",
    )
    parser.add_argument(
        "--name",
        default="Radius",
        help="Name for a new organization row (default: Radius).",
    )
    parser.add_argument(
        "--create-admin-key",
        metavar="KEY_NAME",
        help="Also create a managed API key with this name and print its token once.",
    )
    parser.add_argument(
        "--scopes",
        default=SCOPE_ADMIN,
        help="Comma-separated scopes for --create-admin-key (default: admin).",
    )
    return parser


def _info(message: str) -> None:
    print(message, file=sys.stderr)


def _organization_id(raw: str | None) -> UUID:
    value = (raw or "").strip() or next(
        (os.environ[n].strip() for n in ORG_ID_ENV if os.environ.get(n, "").strip()), ""
    )
    if not value:
        msg = "Pass --organization-id or set GITHUB_DEFAULT_ORGANIZATION_ID."
        raise UsageError(msg)
    try:
        return UUID(value)
    except ValueError:
        msg = f"Organization id {value!r} is not a valid UUID."
        raise UsageError(msg) from None


def _settings() -> ApiSettings:
    try:
        return ApiSettings()
    except SettingsError as exc:
        # Only locations and messages: pydantic's str() would echo input values (secrets).
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'settings'}: {err['msg']}"
            for err in exc.errors()
        )
        msg = f"Invalid configuration: {problems}"
        raise UsageError(msg) from None


def run(args: argparse.Namespace) -> int:
    organization_id = _organization_id(args.organization_id)
    name = args.name.strip()
    if not name or len(name) > 255:
        msg = "--name must be 1 to 255 characters."
        raise UsageError(msg)
    key_name = None if args.create_admin_key is None else args.create_admin_key.strip()
    if key_name is not None and not 0 < len(key_name) <= 120:
        msg = "--create-admin-key needs a key name of 1 to 120 characters."
        raise UsageError(msg)
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    settings = _settings()
    if key_name is not None and not settings.api_key_pepper:
        msg = (
            "Refusing to create a key: RADIUS_API_KEY_PEPPER is not set. Use the same "
            "value as the API (keys fingerprinted with another pepper never authenticate)."
        )
        raise UsageError(msg)

    engine = create_database_engine(settings)
    try:
        required = [Organization.__tablename__]
        if key_name is not None:
            required += [ApiKey.__tablename__, ApiKeyAuditEvent.__tablename__]
        inspector = inspect(engine)
        missing = [table for table in required if not inspector.has_table(table)]
        if missing:
            _info(
                f"Database is not migrated (missing table(s): {', '.join(missing)}). "
                "Run `python -m alembic upgrade head` first."
            )
            return EXIT_FAILURE
        token = None
        with session_scope(create_session_factory(engine)) as session:
            org = session.get(Organization, organization_id)
            if org is None:
                session.add(Organization(id=organization_id, name=name))
                session.flush()
                _info(f"Created organization {organization_id} ({name!r}).")
            else:
                _info(
                    f"Organization {organization_id} already exists ({org.name!r}); left unchanged."
                )
            if key_name is not None:
                service = ApiKeyService(
                    SqlAlchemyApiKeyStore(session), pepper=settings.api_key_pepper
                )
                now = datetime.now(UTC)
                active = [
                    k
                    for k in service.list(organization_id)
                    if k.name == key_name
                    and k.revoked_at is None
                    and (k.expires_at is None or aware(k.expires_at) > now)
                ]
                if active:
                    _info(
                        f"An active key named {key_name!r} already exists (prefix "
                        f"{active[0].prefix}); no new key created. Revoke it or pick another name."
                    )
                else:
                    key, token = service.create(
                        organization_id, name=key_name, scopes=scopes, actor=ACTOR
                    )
                    _info(
                        f"Created API key {key.prefix} with scopes {', '.join(key.scopes)}."
                    )
        if token is not None:
            _info(
                "WARNING: the token below is shown ONCE and is not stored anywhere. "
                "Put it in your secret store now; do not paste it into tickets or logs."
            )
            print(token)
        return EXIT_OK
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse exits with 2 on bad usage
    try:
        return run(args)
    except (UsageError, ValidationError) as exc:
        _info(f"error: {exc}")
        return EXIT_USAGE
    except SQLAlchemyError as exc:
        # The type only: driver messages can include connection details.
        _info(
            f"error: database operation failed ({type(exc).__name__}). Check DATABASE_URL."
        )
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
