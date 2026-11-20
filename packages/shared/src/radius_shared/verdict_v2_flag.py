"""Tri-state flag ``RADIUS_FEATURE_VERDICT_V2`` shared by the API and the worker.

``off`` (default; also unset, ``false``, ``0``, ``no`` and any unrecognised
value, so a typo can never switch v2 on), ``shadow`` (compute and store, keep
publishing v1) and ``on`` (``true``, ``1``, ``yes``; publish v2 when it succeeded).
One pair of matching surrounding quotes is ignored (``"on"``, ``'shadow'``): some
env-file loaders keep them, which silently turned v2 off.
"""

from enum import StrEnum

FLAG_ENV_NAME = "RADIUS_FEATURE_VERDICT_V2"


class VerdictV2Mode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ON = "on"


_ON = {"on", "true", "1", "yes"}
_OFF = {"off", "false", "0", "no", ""}


def parse_verdict_v2_mode(value: object) -> VerdictV2Mode:
    """Parse a flag value; anything unrecognised is ``off`` (fail closed)."""

    if isinstance(value, VerdictV2Mode):
        return value
    if isinstance(value, bool):
        return VerdictV2Mode.ON if value else VerdictV2Mode.OFF
    if value is None:
        return VerdictV2Mode.OFF
    text = _unquote(str(value).strip()).strip().lower()
    if text in _ON:
        return VerdictV2Mode.ON
    if text == "shadow":
        return VerdictV2Mode.SHADOW
    return VerdictV2Mode.OFF


def _unquote(text: str) -> str:
    """Drop one pair of matching surrounding quotes, if any."""

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text
