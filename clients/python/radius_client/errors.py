"""Typed errors raised by the Radius client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RadiusError(Exception):
    """Base class of every error raised by this package."""


class TransportError(RadiusError):
    """The request never produced an HTTP response (DNS, connect, timeout...)."""


class ApiError(RadiusError):
    """The API answered with a non-2xx status.

    ``code`` and ``message`` come from the ``{error: {code, message}}`` envelope
    when present; branch on ``code``, not on ``message``.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.headers: Mapping[str, str] = headers or {}
        self.body = body

    @property
    def request_id(self) -> str | None:
        """Value of ``X-Request-ID`` for support requests, if the server sent one."""

        return self.headers.get("x-request-id")


class BadRequestError(ApiError):
    """400."""


class AuthError(ApiError):
    """401 or 403: missing or invalid API key / organization."""


class NotFoundError(ApiError):
    """404 (also for resources of other organizations)."""


class ConflictError(ApiError):
    """409: wrong state, superseded commit, analysis not completed, ..."""


class StaleEtagError(ConflictError):
    """409 ``INTENT_STALE``: re-read the resource and retry with the new ETag."""


class PayloadTooLargeError(ApiError):
    """413."""


class UnsupportedMediaTypeError(ApiError):
    """415."""


class ValidationFailedError(ApiError):
    """422: the request was understood but is invalid."""


class RateLimitedError(ApiError):
    """429 after the configured retries were exhausted."""

    @property
    def retry_after(self) -> float | None:
        """Seconds the server asked to wait (``Retry-After``), if parseable."""

        raw = self.headers.get("retry-after")
        try:
            return None if raw is None else float(raw)
        except ValueError:
            return None


class ServerError(ApiError):
    """5xx."""


_BY_STATUS: dict[int, type[ApiError]] = {
    400: BadRequestError,
    401: AuthError,
    403: AuthError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    415: UnsupportedMediaTypeError,
    422: ValidationFailedError,
    429: RateLimitedError,
}


def error_from_response(
    status: int, headers: Mapping[str, str], body: Any
) -> ApiError:
    """Build the most specific ``ApiError`` for an error response."""

    code, message = "HTTP_ERROR", f"HTTP {status}"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", code))
            message = str(error.get("message", message))
        elif isinstance(body.get("detail"), str):
            message = body["detail"]
        elif isinstance(body.get("detail"), list):
            code = "VALIDATION_ERROR"
            message = "; ".join(
                str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                for item in body["detail"]
            )
    cls: type[ApiError] = _BY_STATUS.get(status) or (
        ServerError if status >= 500 else ApiError
    )
    if cls is ConflictError and code == "INTENT_STALE":
        cls = StaleEtagError
    return cls(status, code, message, headers=headers, body=body)
