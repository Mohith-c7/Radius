"""Anthropic adapter for :class:`LlmProvider` (optional extra ``llm``).

* The ``anthropic`` SDK is imported lazily, only when a client is first needed,
  so importing this module (and all tests) never requires it.
* The API key comes from the environment (``ANTHROPIC_API_KEY``) only: it is
  not a constructor argument and is never logged.
* Default model: ``claude-haiku-5-5`` (see ``config.DEFAULT_MODEL``). The task
  is short, schema-constrained quote extraction where every output is
  verified against the source anyway, so the cheapest current tier is the
  right default; set ``RADIUS_LLM_INTENT_MODEL=claude-sonnet-5-5`` if the gold
  set (IN-09/IN-10) shows recall is limited by the model.
* Determinism: current Claude models reject non-default sampling parameters
  (and the Messages API accepts no ``seed``), so ``temperature`` is only sent
  when explicitly configured and ``request.seed`` is accepted but NOT sent.
  Reproducibility therefore comes from the response cache plus low effort,
  and is best-effort only.
* SDK-level retries are disabled (``max_retries=0``): the extractor owns
  retry, backoff and the circuit breaker.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from radius_intent.infrastructure.llm.config import DEFAULT_MODEL
from radius_intent.infrastructure.llm.provider import (
    LlmRequest,
    LlmResponse,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimited,
    ProviderRequestError,
    ProviderTimeout,
    ProviderUnavailable,
)

API_KEY_ENV = "ANTHROPIC_API_KEY"


def map_anthropic_error(exc: BaseException) -> ProviderError:
    """Translate an SDK exception (matched by class name, no import needed)."""

    names = {c.__name__ for c in type(exc).__mro__}
    status = getattr(exc, "status_code", None)
    if "APITimeoutError" in names:
        return ProviderTimeout("timeout")
    if "RateLimitError" in names or status == 429:
        return ProviderRateLimited("rate limited")
    if names & {"AuthenticationError", "PermissionDeniedError"} or status in (401, 403):
        return ProviderAuthError("authentication failed")
    if "APIConnectionError" in names:
        return ProviderUnavailable("connection error")
    if isinstance(status, int) and (status >= 500 or status in (408, 409)):
        return ProviderUnavailable(f"server error {status}")
    return ProviderRequestError(f"request rejected ({type(exc).__name__})")


class AnthropicProvider:
    """Messages API adapter. Pass ``client`` to inject a stub in tests."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
        effort: str | None = "low",
        temperature: float | None = None,
    ) -> None:
        self._model = model
        self._client = client
        self._environ = os.environ if environ is None else environ
        self._effort = effort
        self._temperature = temperature

    @property
    def model_id(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        key = self._environ.get(API_KEY_ENV, "").strip()
        if not key:
            raise ProviderConfigError(f"{API_KEY_ENV} is not set")
        try:
            import anthropic  # lazy: optional extra "llm"
        except ImportError as exc:
            raise ProviderConfigError(
                'the "anthropic" package is not installed (pip install ".[llm]")'
            ) from exc
        self._client = anthropic.Anthropic(api_key=key, max_retries=0)
        return self._client

    def build_request(self, request: LlmRequest) -> dict[str, Any]:
        """Keyword arguments for ``client.messages.create`` (unit-testable)."""

        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "timeout": request.timeout_s,
        }
        if self._effort:
            params["output_config"] = {"effort": self._effort}
        if self._temperature is not None:
            params["temperature"] = self._temperature
        return params

    def complete(self, request: LlmRequest) -> LlmResponse:
        client = self._get_client()
        try:
            message = client.messages.create(**self.build_request(request))
        except ProviderError:
            raise
        except Exception as exc:
            raise map_anthropic_error(exc) from None
        if getattr(message, "stop_reason", None) == "refusal":
            raise ProviderRequestError("model refused the request")
        text = "".join(
            getattr(b, "text", "")
            for b in getattr(message, "content", [])
            if getattr(b, "type", None) == "text"
        )
        usage = getattr(message, "usage", None)
        return LlmResponse(
            text,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
