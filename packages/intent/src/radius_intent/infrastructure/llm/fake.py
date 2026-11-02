"""Deterministic fake provider. No network, no keys. For tests and local dev."""

from __future__ import annotations

import json
from collections.abc import Callable

from radius_intent.infrastructure.llm.provider import (
    LlmRequest,
    LlmResponse,
    ProviderError,
)


class FakeProvider:
    """Replies via ``handler(request)`` (a string, or an exception to raise).

    Records every request in ``calls``. With no handler it returns an empty
    criteria document.
    """

    def __init__(
        self,
        handler: Callable[[LlmRequest], str | ProviderError] | None = None,
        *,
        model_id: str = "fake-model-1",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self._handler = handler
        self._model_id = model_id
        self._in = input_tokens
        self._out = output_tokens
        self.calls: list[LlmRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        out = self._handler(request) if self._handler else json.dumps({"criteria": []})
        if isinstance(out, BaseException):
            raise out
        return LlmResponse(out, self._in, self._out)
