"""Request body size limits and content-type enforcement (pure ASGI)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from radius_shared.logging import get_logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radius_api.middleware.errors import error_envelope

LOGGER = get_logger(__name__)

WEBHOOK_PATH = "/api/v1/webhooks/github"
_UPLOAD_PATH = re.compile(r"^/api/v1/analyses/[^/]+/tests/results/?$")
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


@dataclass(frozen=True, slots=True)
class BodyLimits:
    """Maximum request body sizes in bytes."""

    default: int
    webhook: int
    upload: int

    def for_path(self, path: str) -> int:
        if path.rstrip("/") == WEBHOOK_PATH:
            return self.webhook
        if _UPLOAD_PATH.match(path):
            return self.upload
        return self.default


def _allowed_content_types(path: str) -> tuple[str, ...] | None:
    """Return allowed media types, or ``None`` when any type is accepted."""

    if _UPLOAD_PATH.match(path) or path.rstrip("/") == WEBHOOK_PATH:
        # Raw CI reports are validated by the route; webhook bodies are
        # authenticated by HMAC over the exact bytes, whatever the media type.
        return None
    return ("application/json",)


def _media_type_ok(content_type: str, allowed: tuple[str, ...]) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    if media in allowed:
        return True
    return "application/json" in allowed and media.endswith("+json")


class _TooLarge(Exception):
    """Raised from ``receive`` when a streamed body exceeds the limit."""


class RequestLimitsMiddleware:
    """Reject oversized (413) and wrongly typed (415) bodies with the API envelope.

    Declared ``Content-Length`` is checked up front. Chunked or lying clients
    are counted while the body is read; because FastAPI may turn a read error
    into its own 400, the oversize flag also rewrites whatever the app sends.
    """

    def __init__(self, app: ASGIApp, *, limits: BodyLimits) -> None:
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope["method"].upper()
        path = scope["path"]
        headers = {k: v for k, v in scope["headers"]}
        limit = self.limits.for_path(path)

        declared = headers.get(b"content-length")
        if declared is not None:
            text = declared.decode("latin-1").strip()
            if not text.isdigit():
                await self._reply(scope, receive, send, 400, "INVALID_CONTENT_LENGTH",
                                  "Content-Length must be a non-negative integer.")
                return
            if int(text) > limit:
                await self._too_large(scope, receive, send, limit)
                return
        has_body = (declared is not None and int(declared) > 0) or (
            b"transfer-encoding" in headers
        )

        if method in _BODY_METHODS and has_body:
            allowed = _allowed_content_types(path)
            content_type = headers.get(b"content-type", b"").decode("latin-1")
            if allowed is not None and not _media_type_ok(content_type, allowed):
                await self._reply(
                    scope, receive, send, 415, "UNSUPPORTED_MEDIA_TYPE",
                    f"Content-Type must be one of: {', '.join(allowed)}.",
                )
                return

        state = {"seen": 0, "exceeded": False, "started": False, "swallow": False}

        async def counting_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > limit:
                    state["exceeded"] = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            if state["swallow"]:
                return
            if state["exceeded"] and not state["started"]:
                state["swallow"] = True
                state["started"] = True
                await self._too_large(scope, receive, send, limit)
                return
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _TooLarge:
            if not state["started"]:
                state["started"] = True
                state["swallow"] = True
                await self._too_large(scope, receive, send, limit)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        LOGGER.warning("Request body rejected: too large", extra={"limit": limit})
        await self._reply(
            scope, receive, send, 413, "PAYLOAD_TOO_LARGE",
            f"Request body exceeds {limit} bytes.",
            meta={"max_bytes": limit},
        )

    @staticmethod
    async def _reply(scope: Scope, receive: Receive, send: Send, status: int,
                     code: str, message: str, meta: dict[str, object] | None = None) -> None:
        response = error_envelope(
            status, code, message, meta=meta, headers={"Connection": "close"}
        )
        await response(scope, receive, send)
