"""API token generation and fingerprinting (the only place tokens are hashed).

Tokens are 256 bits of CSPRNG output, so a slow password KDF adds nothing: there
is no low-entropy input to stretch. The stored value is a keyed HMAC-SHA256
fingerprint using a server-side pepper (``RADIUS_API_KEY_PEPPER``), so a copy of
the database alone cannot be used to verify or forge tokens.
"""

import hmac
import secrets
from hashlib import sha256

TOKEN_MARKER = "rdk"
_PREFIX_BYTES = 4
_SECRET_BYTES = 32


def new_token() -> tuple[str, str]:
    """Return ``(token, prefix)``; the token is shown to the caller exactly once."""

    prefix = secrets.token_hex(_PREFIX_BYTES)
    return f"{TOKEN_MARKER}_{prefix}_{secrets.token_urlsafe(_SECRET_BYTES)}", prefix


def token_prefix(token: str) -> str | None:
    """Return the public prefix of a managed token, or ``None`` if malformed."""

    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_MARKER or not parts[1] or not parts[2]:
        return None
    return parts[1]


def looks_like_managed_token(value: str | None) -> bool:
    """Return whether ``value`` has the managed-token marker."""

    return bool(value) and value.startswith(f"{TOKEN_MARKER}_")


def token_fingerprint(token: str, pepper: str) -> str:
    """Return the keyed fingerprint (hex HMAC-SHA256) stored for ``token``."""

    return hmac.new(pepper.encode(), token.encode(), sha256).hexdigest()


def fingerprints_match(left: str, right: str) -> bool:
    """Constant-time fingerprint comparison."""

    return hmac.compare_digest(left.encode(), right.encode())
