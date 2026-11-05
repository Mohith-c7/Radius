"""Validation of git clone URLs (security boundary).

A clone URL is data from a caller or from a database row and ends up as an
argument of ``git``. It must therefore be an ``https`` URL on an allow-listed
host with the shape ``https://<host>/<owner>/<repo>[.git]``; anything else
(``--upload-pack=...`` style options, ``file://``, ``ext::``, local paths,
scp-like ``user@host:path``, credentials in the URL, control characters) is
refused. The same check runs at the API boundary and again, defensively, in the
worker right before git is invoked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from radius_shared.errors import ValidationError

DEFAULT_GIT_HOSTS: tuple[str, ...] = ("github.com",)
MAX_CLONE_URL_LENGTH = 300

# GitHub owner/repo names: letters, digits, '-', '_', '.'; never '.' or '..'.
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_FORBIDDEN_CHARS = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class GitUrlPolicy:
    """Which remotes git may talk to.

    ``allow_http`` exists for tests that use a loopback HTTP server; it is never
    set from configuration.
    """

    allowed_hosts: tuple[str, ...] = DEFAULT_GIT_HOSTS
    allow_http: bool = False


def parse_allowed_hosts(value: str | None) -> tuple[str, ...]:
    """Parse a comma separated host list; blank means the default (github.com)."""

    hosts = tuple(
        item.strip().lower().rstrip(".")
        for item in (value or "").split(",")
        if item.strip()
    )
    for host in hosts:
        if not _HOST.match(host):
            msg = f"Invalid git host {host!r} in RADIUS_GIT_ALLOWED_HOSTS."
            raise ValueError(msg)
    return hosts or DEFAULT_GIT_HOSTS


def _invalid(reason: str) -> ValidationError:
    return ValidationError(f"Invalid clone URL: {reason}.")


def validate_clone_url(
    url: object,
    *,
    policy: GitUrlPolicy | None = None,
) -> str:
    """Return the canonical clone URL or raise ``ValidationError``.

    The returned value is always ``https://<host>/<owner>/<repo>.git`` (``http``
    only when the policy allows it), built from the parsed parts, never the raw
    input.
    """

    policy = policy or GitUrlPolicy()
    if not isinstance(url, str) or not url:
        raise _invalid("a non-empty string is required")
    if len(url) > MAX_CLONE_URL_LENGTH:
        raise _invalid("too long")
    if url.startswith("-"):
        raise _invalid("must not start with '-'")
    if _FORBIDDEN_CHARS.search(url):
        raise _invalid("whitespace and control characters are not allowed")
    scheme = "https"
    if not url.startswith("https://"):
        if not (policy.allow_http and url.startswith("http://")):
            raise _invalid("only https:// URLs are allowed")
        scheme = "http"
    try:
        parts = urlsplit(url)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise _invalid("malformed URL") from None
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise _invalid("query strings and fragments are not allowed")
    if "@" in parts.netloc or parts.username or parts.password:
        raise _invalid("credentials in the URL are not allowed")
    if not hostname or hostname.lower() not in policy.allowed_hosts:
        raise _invalid("host is not allowed")
    if port is not None and not (policy.allow_http and scheme == "http"):
        if port != 443:
            raise _invalid("custom ports are not allowed")
    segments = parts.path.lstrip("/").split("/")
    if parts.path.startswith("//") or len(segments) != 2:
        raise _invalid("the path must be /<owner>/<repository>[.git]")
    owner, repo = segments
    repo = repo.removesuffix(".git")
    for segment in (owner, repo):
        if segment in {"", ".", ".."} or not _NAME.match(segment):
            raise _invalid("owner or repository name is not valid")
    keep_port = port is not None and scheme == "http"
    netloc = f"{hostname.lower()}:{port}" if keep_port else hostname.lower()
    return f"{scheme}://{netloc}/{owner}/{repo}.git"


def clone_url_names(clone_url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` from an already validated canonical clone URL."""

    owner, repo = urlsplit(clone_url).path.lstrip("/").split("/")
    return owner, repo.removesuffix(".git")


def clone_url_matches(clone_url: str, owner: str, name: str) -> bool:
    """Whether a validated clone URL names exactly ``owner/name`` (case-insensitive)."""

    url_owner, url_repo = clone_url_names(clone_url)
    return (url_owner.lower(), url_repo.lower()) == (owner.lower(), name.lower())


def host_of(url: str | None) -> str | None:
    """Lower-case hostname of ``url`` or ``None`` when it has none."""

    if not url:
        return None
    try:
        return (urlsplit(url).hostname or "").lower() or None
    except ValueError:
        return None
