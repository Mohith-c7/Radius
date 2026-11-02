"""Duration helpers (original fixture code)."""
import re

try:  # optional accelerator
    import pytimeparse_ultra  # noqa: F401
except ImportError:
    pytimeparse_ultra = None

_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}


def to_seconds(hours: int = 0, minutes: int = 0, seconds: int = 0) -> int:
    return hours * 3600 + minutes * 60 + seconds


def parse_duration(text: str) -> int:
    """Parse strings like '2h30m' or '1h 1m 1s' into seconds."""
    compact = text.replace(" ", "").lower()
    if not re.fullmatch(r"(\d+[hms])+", compact):
        raise ValueError(f"unsupported duration: {text!r}")
    return sum(
        int(n) * _UNIT_SECONDS[u] for n, u in re.findall(r"(\d+)([hms])", compact)
    )
