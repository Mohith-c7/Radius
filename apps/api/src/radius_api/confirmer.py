"""Who is acting on a criterion: the audit actor of an intent write (B-07, DEC-040).

The actor is taken from the *authenticated principal*, never from a free-text header:

* ``X-Radius-Session`` (sent only by the dashboard proxy, never by a browser; it is not in the
  CORS allow list): the signed session token of a signed-in user. It is validated exactly
  like the session cookie (signature, live row, not revoked, not expired). The actor becomes
  ``org:<id>/user=<user id>`` and, when that user signed in with GitHub, ``/gh=<login>``
  from the stored OAuth link (``auth_accounts.provider_login``).
* otherwise the API credential: ``/key=<key prefix>`` (managed key), ``/legacy-env-key`` or
  ``/dev=<label>`` (only in the insecure development mode, where the old ``X-Radius-Actor``
  label is still accepted so the local demo keeps working; it is marked ``dev=`` and counted
  as unverified).

``X-Radius-Actor`` is ignored whenever the API runs with real credentials. The worker parses
the same string (``radius_worker.verdict_v2.intent_refresh.parse_actor``). Characters:
``=`` cannot appear in an old label (the label pattern excludes it), so the structured
form cannot be forged by a label.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from radius_api.auth import ApiPrincipal

SESSION_HEADER = "X-Radius-Session"


def _session_user(token: str, db: Session) -> tuple[str, str | None]:
    """``(user id, GitHub login or None)`` of a valid session token; 401 otherwise."""

    from app.models import AuthAccount
    from app.routes_auth import _load_session

    user, _ = _load_session(token, db)
    login = db.scalar(
        select(AuthAccount.provider_login).where(
            AuthAccount.user_id == user.id, AuthAccount.provider == "github"
        )
    )
    return str(user.id), (login if isinstance(login, str) and login else None)


def resolve_actor(
    principal: ApiPrincipal,
    *,
    session_token: str | None,
    label: str | None,
    auth_db: Session,
) -> str:
    """The audit actor for an intent write (see the module docstring)."""

    base = f"org:{principal.organization_id}"
    if session_token:
        user_id, login = _session_user(session_token, auth_db)
        return f"{base}/user={user_id}" + (f"/gh={login}" if login else "")
    if principal.source == "managed" and principal.key_prefix:
        return f"{base}/key={principal.key_prefix}"
    if principal.source == "dev":
        return f"{base}/dev={label}" if label else f"{base}/dev"
    return f"{base}/legacy-env-key"
