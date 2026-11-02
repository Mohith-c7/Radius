"""Text helpers (original fixture code)."""
import re


def title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


def slugify(title: str) -> str:
    """Lowercase, collapse non-alphanumeric runs to '-', trim '-' at the ends."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
