"""Email helpers (original fixture code)."""


def domain_of(addr: str) -> str:
    return addr.split("@", 1)[1]


def normalize_email(addr: str) -> str:
    """Trim surrounding whitespace and lowercase; require an '@'."""
    cleaned = addr.strip().lower()
    if "@" not in cleaned:
        raise ValueError("not an email address")
    return cleaned
