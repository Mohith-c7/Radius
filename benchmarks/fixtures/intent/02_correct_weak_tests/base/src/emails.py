"""Email helpers (original fixture code)."""


def domain_of(addr: str) -> str:
    return addr.split("@", 1)[1]
