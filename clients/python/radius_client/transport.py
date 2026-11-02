"""HTTP transports. The client only needs ``Transport.request``."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from radius_client.errors import TransportError


@dataclass(frozen=True)
class TransportResponse:
    """A raw HTTP response. Header names are lower-cased."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


class Transport(Protocol):
    """Anything that can perform one HTTP request."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> TransportResponse:
        """Perform the request; return error statuses as responses, do not raise."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: they would replay credentials to another host."""

    def redirect_request(self, *args, **kwargs):  # type: ignore[override]
        return None


class UrllibTransport:
    """Default transport built on the standard library."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> TransportResponse:
        if not url.lower().startswith(("http://", "https://")):
            msg = f"Unsupported URL scheme: {url!r}"
            raise TransportError(msg)
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))  # noqa: S310
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return _to_response(resp.status, resp.headers.items(), resp.read())
        except urllib.error.HTTPError as exc:
            return _to_response(exc.code, exc.headers.items(), exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc


def _to_response(status: int, headers, body: bytes) -> TransportResponse:
    return TransportResponse(
        status=status,
        headers={name.lower(): value for name, value in headers},
        body=body,
    )
