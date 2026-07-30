"""Standard API response envelopes."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ErrorResponse(BaseModel):
    """Typed error payload returned by Radius APIs."""

    code: str
    message: str


class ApiResponse(BaseModel, Generic[DataT]):
    """Consistent response envelope for Radius APIs."""

    success: bool
    data: DataT | None = None
    error: ErrorResponse | None = None
    meta: dict[str, object] = Field(default_factory=dict)


def success_response(
    data: DataT,
    meta: dict[str, object] | None = None,
) -> ApiResponse[DataT]:
    """Create a successful API response envelope."""

    return ApiResponse(success=True, data=data, meta=meta or {})


def error_response(
    code: str,
    message: str,
    meta: dict[str, object] | None = None,
) -> ApiResponse[None]:
    """Create a failed API response envelope."""

    return ApiResponse(
        success=False,
        error=ErrorResponse(code=code, message=message),
        meta=meta or {},
    )
