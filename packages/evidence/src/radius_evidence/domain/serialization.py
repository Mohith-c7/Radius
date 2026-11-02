"""Stable JSON (de)serialization for the frozen contract dataclasses.

Rules (design section 3): sorted keys, floats rounded to 6 decimals, tuples and
sets become lists (sets sorted), enums become their value, no clocks. Unknown
keys are ignored on read so newer payloads stay readable.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import types
import typing
from enum import Enum
from typing import Any, ClassVar, Self

FLOAT_DECIMALS = 6


def encode(value: Any) -> Any:
    """Convert a contract value into plain JSON types."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, FLOAT_DECIMALS)
    if isinstance(value, (set, frozenset)):
        return sorted((encode(v) for v in value), key=_sort_key)
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    msg = f"cannot serialize {type(value).__name__}"
    raise TypeError(msg)


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def canonical_json(value: Any) -> str:
    """Compact JSON with sorted keys; equal inputs give identical bytes."""

    return json.dumps(
        encode(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_hex(text: str) -> str:
    """Return the 64-character hex SHA-256 of ``text`` (UTF-8)."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decode(tp: Any, value: Any) -> Any:
    """Convert plain JSON data to the annotated type ``tp``."""

    if tp is Any or tp is object:
        return value
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        rest = [a for a in args if a is not type(None)]
        return decode(rest[0], value)
    if origin is tuple:
        return tuple(decode(args[0], v) for v in value) if args else tuple(value)
    if origin in (frozenset, set):
        return frozenset(decode(args[0], v) for v in value)
    if origin is list:
        return [decode(args[0], v) for v in value]
    if origin is dict:
        item = args[1] if len(args) == 2 else Any
        return {k: decode(item, v) for k, v in value.items()}
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return from_dict(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is float:
            return float(value)
        if tp is int and not isinstance(value, bool):
            return int(value)
    return value


def from_dict[T](cls: type[T], data: dict[str, Any]) -> T:
    """Build dataclass ``cls`` from ``data``; unknown keys are ignored."""

    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if f.init and f.name in data:
            kwargs[f.name] = decode(hints[f.name], data[f.name])
    return cls(**kwargs)


class Serializable:
    """Mixin giving a contract dataclass ``to_dict``/``from_dict``/JSON helpers."""

    __slots__ = ()
    __dataclass_fields__: ClassVar[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return encode(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return from_dict(cls, data)

    @classmethod
    def from_json(cls, text: str) -> Self:
        return from_dict(cls, json.loads(text))
