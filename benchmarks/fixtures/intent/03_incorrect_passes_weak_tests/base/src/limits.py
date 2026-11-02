"""Numeric limit helpers (original fixture code)."""


def is_between(value: int, lo: int, hi: int) -> bool:
    return lo <= value <= hi
