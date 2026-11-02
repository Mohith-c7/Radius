"""Duration helpers (original fixture code)."""


def to_seconds(hours: int = 0, minutes: int = 0, seconds: int = 0) -> int:
    return hours * 3600 + minutes * 60 + seconds
