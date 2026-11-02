"""Provider port for LLM-assisted extraction (IN-04, DEC-015).

The extractor depends only on :class:`LlmProvider`. Real SDK adapters live in
their own modules (``anthropic_provider``) and are imported lazily; tests use
:mod:`radius_intent.infrastructure.llm.fake`. No network code is in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LlmRequest:
    """One completion request. ``user`` carries only delimited, redacted data."""

    system: str
    user: str
    max_output_tokens: int = 2048
    timeout_s: float = 30.0
    seed: int | None = None  # best-effort; not every provider honours it


@dataclass(frozen=True)
class LlmResponse:
    """Raw model text plus provider-reported token usage (0 when unknown)."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """Base class. ``retryable`` tells the extractor whether to back off and retry."""

    code = "provider_error"
    retryable = False


class ProviderTimeout(ProviderError):
    code = "timeout"
    retryable = True


class ProviderRateLimited(ProviderError):
    code = "rate_limited"
    retryable = True


class ProviderUnavailable(ProviderError):
    code = "unavailable"
    retryable = True


class ProviderAuthError(ProviderError):
    code = "auth"


class ProviderRequestError(ProviderError):
    code = "bad_request"


class ProviderConfigError(ProviderError):
    """Missing SDK or credentials. Raised when the adapter is built or first used."""

    code = "config"


class LlmProvider(Protocol):
    """A text-in, text-out model. No tools, no streaming, no side effects."""

    @property
    def model_id(self) -> str: ...

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the model's reply or raise a :class:`ProviderError`."""
