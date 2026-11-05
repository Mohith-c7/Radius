"""Typed, dependency-free Python client for the stable Radius HTTP API.

    from radius_client import RadiusClient

    client = RadiusClient("https://radius.example.com", ORG_ID, API_KEY)
    for analysis in client.list_analyses(status="completed"):
        print(analysis["id"], analysis["commit_sha"])

See ``clients/python/README.md`` and ``docs/api/STABILITY.md``.
"""

from radius_client.client import RadiusClient, parse_retry_after
from radius_client.errors import (
    ApiError,
    AuthError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    RadiusError,
    RateLimitedError,
    ServerError,
    StaleEtagError,
    TransportError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)
from radius_client.models import (
    Analysis,
    ConfidenceReport,
    Criterion,
    CriterionResult,
    IntentSnapshot,
    UploadResult,
    Versioned,
)
from radius_client.transport import Transport, TransportResponse, UrllibTransport

__version__ = "0.1.0"

__all__ = [
    "Analysis",
    "ApiError",
    "AuthError",
    "BadRequestError",
    "ConfidenceReport",
    "ConflictError",
    "Criterion",
    "CriterionResult",
    "IntentSnapshot",
    "NotFoundError",
    "PayloadTooLargeError",
    "RadiusClient",
    "RadiusError",
    "RateLimitedError",
    "ServerError",
    "StaleEtagError",
    "Transport",
    "TransportError",
    "TransportResponse",
    "UnsupportedMediaTypeError",
    "UploadResult",
    "UrllibTransport",
    "ValidationFailedError",
    "Versioned",
    "__version__",
    "parse_retry_after",
]
