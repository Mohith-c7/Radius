"""Security headers for every API response (pure ASGI, so errors get them too)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: API responses are JSON data, never documents: nothing may load or frame them.
API_CSP = "default-src 'none'; frame-ancestors 'none'"

#: Swagger UI / ReDoc need their CDN assets; everything else stays locked down.
DOCS_CSP = (
    "default-src 'none'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; worker-src blob:; frame-ancestors 'none'"
)
DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


class SecurityHeadersMiddleware:
    """Add hardening headers; handler-set values are never overwritten."""

    def __init__(self, app: ASGIApp, *, hsts_enabled: bool = False,
                 hsts_max_age: int = 31536000) -> None:
        self.app = app
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age = hsts_max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        csp = DOCS_CSP if scope.get("path", "") in DOCS_PATHS else API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                defaults = {
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "Permissions-Policy": PERMISSIONS_POLICY,
                    "Cross-Origin-Opener-Policy": "same-origin",
                    "Cross-Origin-Resource-Policy": "same-site",
                    "X-Frame-Options": "DENY",
                    "Content-Security-Policy": csp,
                    "Cache-Control": "no-store",
                }
                if self.hsts_enabled:
                    defaults["Strict-Transport-Security"] = (
                        f"max-age={self.hsts_max_age}; includeSubDomains"
                    )
                for name, value in defaults.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
