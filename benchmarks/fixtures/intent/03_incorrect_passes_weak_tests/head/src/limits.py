"""Numeric limit helpers (original fixture code)."""


def is_between(value: int, lo: int, hi: int) -> bool:
    return lo <= value <= hi


def clamp(value: int, lo: int, hi: int) -> int:
    """Limit value to the closed range [lo, hi]."""
    if value > hi:
        return hi
    return value
