"""Input validators (original fixture code)."""


def is_blank(text: str) -> bool:
    return not text.strip()
