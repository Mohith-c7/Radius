"""Correlation identifiers carried through contextvars.

The ids bound here (``analysis_id``, ``job_id``, ``delivery_id``,
``organization_id``, ``request_id``) are added to every structured log record
and, when tracing is enabled, to spans. ``contextvars`` keep them isolated per
request/thread/task, so concurrent requests never see each other's ids.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

CORRELATION_KEYS = (
    "request_id",
    "organization_id",
    "delivery_id",
    "analysis_id",
    "job_id",
)

_CONTEXT: ContextVar[Mapping[str, str]] = ContextVar(
    "radius_correlation_context", default=MappingProxyType({})
)


def get_correlation_context() -> dict[str, str]:
    """Return a copy of the currently bound correlation ids."""

    return dict(_CONTEXT.get())


@contextmanager
def bind_correlation(**ids: Any) -> Iterator[None]:
    """Bind correlation ids for the duration of the ``with`` block.

    ``None`` values are ignored; values are stringified. Nested blocks extend
    (and may override) the outer ids; the previous state is restored on exit.
    """

    unknown = set(ids) - set(CORRELATION_KEYS)
    if unknown:
        msg = f"Unknown correlation keys: {sorted(unknown)}"
        raise ValueError(msg)
    merged = dict(_CONTEXT.get())
    merged.update({key: str(value) for key, value in ids.items() if value is not None})
    token = _CONTEXT.set(merged)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def update_correlation(**ids: Any) -> None:
    """Add ids to the current context without a block (lives until it ends).

    Use where a ``with`` block is impractical, e.g. once a request handler has
    resolved the delivery and tenant. Each request/task has its own context,
    so this never leaks into other requests.
    """

    unknown = set(ids) - set(CORRELATION_KEYS)
    if unknown:
        msg = f"Unknown correlation keys: {sorted(unknown)}"
        raise ValueError(msg)
    merged = dict(_CONTEXT.get())
    merged.update({key: str(value) for key, value in ids.items() if value is not None})
    _CONTEXT.set(merged)
