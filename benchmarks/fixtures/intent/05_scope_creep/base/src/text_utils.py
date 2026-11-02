"""Text helpers (original fixture code)."""


def title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())
