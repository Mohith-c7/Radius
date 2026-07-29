"""Shared application errors."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Serializable error detail."""

    code: str
    message: str


class RadiusError(Exception):
    """Base error for expected Radius application failures."""

    code = "RADIUS_ERROR"
    message = "A Radius error occurred."

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        self.detail = ErrorDetail(
            code=code or self.code,
            message=message or self.message,
        )
        super().__init__(self.detail.message)


class ValidationError(RadiusError):
    """Raised when input validation fails."""

    code = "VALIDATION_ERROR"
    message = "The request could not be validated."


class NotFoundError(RadiusError):
    """Raised when an expected resource does not exist."""

    code = "NOT_FOUND"
    message = "The requested resource does not exist."


class AccessDeniedError(RadiusError):
    """Raised when an actor is not authorized for an action."""

    code = "ACCESS_DENIED"
    message = "Access denied."
