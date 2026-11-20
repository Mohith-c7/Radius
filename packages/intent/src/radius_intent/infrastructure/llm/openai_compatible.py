"""OpenAI-compatible chat-completions adapter for :class:`LlmProvider` (plain HTTP, httpx).

One adapter covers every provider that speaks ``POST {base_url}/chat/completions`` with a
``Bearer`` key, for example (see ``docs/ai.md``):

* OpenRouter (recommended free option): ``https://openrouter.ai/api/v1`` with ``:free`` models
* Google Gemini (AI Studio key): ``https://generativelanguage.googleapis.com/v1beta/openai/``
* Groq: ``https://api.groq.com/openai/v1``

Design rules:

* No SDK and no backoff here: :class:`radius_intent.infrastructure.llm.guarded.GuardedProvider`
  owns retries with backoff, the call budget, pacing and the deadline.
* Strict timeouts: every request has a connect and a read timeout (``request.timeout_s``).
  Redirects are not followed (a redirect would re-send the ``Authorization`` header).
* The key is a constructor argument held privately; it is never logged, never put in an
  exception message and never in ``repr``. Error messages carry the HTTP status only,
  never the response body (a provider may echo the prompt back).
* Model fallback: ``model`` may list several models (comma-separated); 404, 429 and empty
  replies move on to the next one (free models come and go and are often rate limited).
* Structured output: ``json_mode="json_object"`` (default) sends
  ``{"type": "json_object"}`` for requests that expect JSON (they carry a schema);
  ``schema`` sends that JSON Schema as ``json_schema``; ``off`` sends no
  ``response_format``. If the provider rejects ``response_format`` with HTTP 400, the
  adapter retries once without it and stops sending it. JSON mode is not trusted: a reply
  that does not parse as JSON is re-asked once with a stricter instruction, and the caller
  validates its own schema anyway.
* A reply wrapped in a single Markdown code fence is unwrapped (some models add one).
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from radius_shared.logging import get_logger

from radius_intent.infrastructure.llm.provider import (
    LlmRequest,
    LlmResponse,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderOutputTruncated,
    ProviderRateLimited,
    ProviderRequestError,
    ProviderTimeout,
    ProviderUnavailable,
)

_LOG = get_logger("radius.llm.openai_compatible")

JSON_MODES = frozenset({"json_object", "schema", "off"})
REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high"})
MAX_RESPONSE_BYTES = 1_000_000
MAX_MODELS = 5
STRICT_JSON_SUFFIX = (
    "\nIMPORTANT: your previous reply was not valid JSON. Reply with exactly one JSON object "
    "that matches the schema above: no prose, no Markdown, no code fences.\n"
)
MAX_RETRY_AFTER_S = 3600.0
_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\n(?P<body>.*?)\n?```\s*$", re.DOTALL)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_base_url(base_url: str) -> str:
    """Return the normalised base URL or raise :class:`ProviderConfigError`.

    HTTPS is required; plain HTTP is accepted only for a loopback host (a local
    OpenAI-compatible server such as Ollama), so a key is never sent in clear text.
    """

    url = (base_url or "").strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or parts.username or parts.password or parts.query or parts.fragment:
        raise ProviderConfigError("RADIUS_LLM_BASE_URL is not a valid base URL")
    if parts.scheme == "https":
        return url.rstrip("/")
    if parts.scheme == "http":
        loopback = host in _LOCAL_HOSTS
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
        if loopback:
            return url.rstrip("/")
    raise ProviderConfigError("RADIUS_LLM_BASE_URL must use https (http only for localhost)")


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a ``Retry-After`` header (delta-seconds form only), capped."""

    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)


def unwrap_fence(text: str) -> str:
    """Strip one surrounding Markdown code fence, if the whole reply is fenced."""

    match = _FENCE.match(text)
    return match.group("body") if match else text


def parse_models(value: str) -> tuple[str, ...]:
    """``RADIUS_LLM_MODEL`` as an ordered, de-duplicated fallback list."""

    out: list[str] = []
    for part in (value or "").split(","):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return tuple(out[:MAX_MODELS])


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts
        return "".join(
            str(p.get("text", "")) for p in content if isinstance(p, Mapping)
        )
    return ""


class _ModelUnavailable(Exception):
    """This model cannot answer now (404, 429 or empty reply): try the next one."""

    def __init__(self, error: ProviderError) -> None:
        super().__init__(str(error))
        self.error = error


class OpenAICompatibleProvider:
    """Chat-completions adapter. Pass ``transport`` (an ``httpx`` transport) in tests.

    ``model`` may be a comma-separated fallback list (``RADIUS_LLM_MODEL``). A model that
    answers 404 (slug gone), 429 (rate limited upstream) or an empty reply is skipped for
    the next one; the last model's error is raised. ``request.timeout_s`` bounds the whole
    ``complete`` call, all fallbacks included. ``before_http`` (set by ``GuardedProvider``)
    is called before every HTTP request so pacing and the daily cap count real requests.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        json_mode: str = "json_object",
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        transport: httpx.BaseTransport | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = validate_base_url(base_url) + "/chat/completions"
        if not (api_key or "").strip():
            raise ProviderConfigError("RADIUS_LLM_API_KEY is not set")
        models = parse_models(model)
        if not models:
            raise ProviderConfigError("RADIUS_LLM_MODEL is not set")
        self.__key = api_key.strip()
        self._models = models
        mode = (json_mode or "json_object").strip().lower()
        self._json_mode = mode if mode in JSON_MODES else "json_object"
        effort = (reasoning_effort or "").strip().lower()
        self._effort = effort if effort in REASONING_EFFORTS else None
        self._temperature = temperature
        self._transport = transport
        self._max_bytes = max_response_bytes
        self._clock = clock
        self._format_ok = True
        self.before_http: Callable[[], None] | None = None
        #: The model that produced the last reply (for provenance), or ``None``.
        self.last_model: str | None = None

    def __repr__(self) -> str:  # never include the key
        return f"OpenAICompatibleProvider(models={self._models!r}, url={self._url!r})"

    @property
    def model_id(self) -> str:
        return self._models[0]

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    def build_payload(
        self, request: LlmRequest, *, model: str | None = None, strict_retry: bool = False
    ) -> dict[str, Any]:
        """The JSON body for one request (unit-testable, contains no key)."""

        system = request.system + (STRICT_JSON_SUFFIX if strict_retry else "")
        body: dict[str, Any] = {
            "model": model or self._models[0],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": request.user},
            ],
            "max_tokens": int(request.max_output_tokens),
            "n": 1,
            "stream": False,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._effort:
            body["reasoning_effort"] = self._effort
        if self._format_ok and self._json_mode != "off":
            if self._json_mode == "schema" and request.json_schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name,
                        "schema": dict(request.json_schema),
                        "strict": True,
                    },
                }
            elif request.json_schema is not None:
                body["response_format"] = {"type": "json_object"}
        return body

    def complete(self, request: LlmRequest) -> LlmResponse:
        stop_at = self._clock() + max(0.5, float(request.timeout_s))
        last: ProviderError | None = None
        for model in self._models:
            try:
                response = self._ask(request, model, stop_at)
            except _ModelUnavailable as exc:
                last = exc.error
                _LOG.info(
                    "LLM model unavailable, trying the next one",
                    extra={"outcome": f"llm_model_skip:{exc.error.code}", "model": model},
                )
                continue
            if request.json_schema is not None and not _is_json(response.text):
                # JSON mode is not trusted on its own: re-ask once, more strictly.
                try:
                    again = self._ask(request, model, stop_at, strict_retry=True)
                except (_ModelUnavailable, ProviderError):
                    again = None
                if again is not None and _is_json(again.text):
                    response = again
            self.last_model = model
            return response
        if last is None:  # pragma: no cover - at least one model is configured
            raise ProviderRequestError("no model configured")
        raise last

    # --- one model ----------------------------------------------------------

    def _ask(
        self, request: LlmRequest, model: str, stop_at: float, *, strict_retry: bool = False
    ) -> LlmResponse:
        payload = self.build_payload(request, model=model, strict_retry=strict_retry)
        try:
            return self._parse(self._post(payload, stop_at))
        except ProviderRequestError as exc:
            if "response_format" not in payload or getattr(exc, "status", None) != 400:
                raise
        # The provider refused structured output: retry this request once without it.
        self._format_ok = False
        _LOG.warning(
            "LLM provider rejected response_format; continuing without structured output",
            extra={"outcome": "llm_response_format_unsupported", "model": model},
        )
        payload = self.build_payload(request, model=model, strict_retry=strict_retry)
        return self._parse(self._post(payload, stop_at))

    # --- transport ----------------------------------------------------------

    def _post(self, payload: dict[str, Any], stop_at: float) -> httpx.Response:
        if stop_at - self._clock() < 0.5:
            raise ProviderTimeout("LLM call deadline reached")
        if self.before_http is not None:
            self.before_http()
        remaining = stop_at - self._clock()
        if remaining < 0.5:
            raise ProviderTimeout("LLM call deadline reached")
        headers = {
            "Authorization": f"Bearer {self.__key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "radius-llm/1",
            # OpenRouter attribution (optional there, ignored by other providers).
            "X-Title": "Radius",
            "X-OpenRouter-Title": "Radius",
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(remaining, connect=min(5.0, remaining)),
                follow_redirects=False,
            ) as client:
                response = client.post(self._url, content=json.dumps(payload), headers=headers)
        except httpx.TimeoutException:
            raise ProviderTimeout("timeout") from None
        except httpx.HTTPError:
            raise ProviderUnavailable("connection error") from None
        status = response.status_code
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        if status == 429:
            err = ProviderRateLimited("rate limited (HTTP 429)")
            err.retry_after_s = retry_after
            raise _ModelUnavailable(err)
        if status == 404:
            raise _ModelUnavailable(ProviderRequestError("model not available (HTTP 404)"))
        if status in (401, 403):
            raise ProviderAuthError(f"authentication failed (HTTP {status})")
        if status in (408, 409) or status >= 500:
            err_u = ProviderUnavailable(f"server error (HTTP {status})")
            err_u.retry_after_s = retry_after
            raise err_u
        if status >= 300:
            err_r = ProviderRequestError(f"request rejected (HTTP {status})")
            err_r.status = status  # type: ignore[attr-defined]
            raise err_r
        if len(response.content) > self._max_bytes:
            raise ProviderRequestError("response too large")
        return response

    def _parse(self, response: httpx.Response) -> LlmResponse:
        try:
            data = response.json()
        except ValueError:
            raise ProviderRequestError("response is not JSON") from None
        if not isinstance(data, Mapping):
            raise ProviderRequestError("response is not an object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            # Some gateways (OpenRouter) answer 200 with an upstream error object.
            error = data.get("error") if isinstance(data.get("error"), Mapping) else {}
            code = str(error.get("code", ""))
            if code == "429":
                raise _ModelUnavailable(ProviderRateLimited("rate limited upstream"))
            if code == "404":
                raise _ModelUnavailable(ProviderRequestError("model not available"))
            if error:
                raise ProviderUnavailable("upstream error")
            raise ProviderRequestError("response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first.get("message"), Mapping) else {}
        text = _message_text(message.get("content")).strip()
        finish = str(first.get("finish_reason") or "")
        if finish == "content_filter" or message.get("refusal"):
            raise ProviderRequestError("model refused the request")
        if finish == "length":
            raise ProviderOutputTruncated("reply hit the output token limit")
        if not text:
            raise _ModelUnavailable(ProviderRequestError("empty reply"))
        usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}

        def _tokens(key: str) -> int:
            value = usage.get(key)
            return int(value) if isinstance(value, int) and value > 0 else 0

        return LlmResponse(
            unwrap_fence(text), _tokens("prompt_tokens"), _tokens("completion_tokens")
        )


__all__ = [
    "JSON_MODES",
    "REASONING_EFFORTS",
    "OpenAICompatibleProvider",
    "parse_models",
    "parse_retry_after",
    "unwrap_fence",
    "validate_base_url",
]
