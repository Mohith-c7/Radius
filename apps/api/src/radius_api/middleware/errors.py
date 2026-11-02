"""Error envelopes produced below the FastAPI exception handlers."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from radius_shared.dto import error_response


def error_envelope(
    status_code: int,
    code: str,
    message: str,
    *,
    meta: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return the standard ``{success: false, error: {code, message}}`` response."""

    return JSONResponse(
        status_code=status_code,
        content=error_response(code, message, meta).model_dump(),
        headers=headers,
    )
