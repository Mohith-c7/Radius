"""Input validators (original fixture code)."""

COMMON_PASSWORDS = {"password1", "qwerty123", "welcome1"}


def is_blank(text: str) -> bool:
    return not text.strip()


def validate_password(pw: str) -> bool:
    if len(pw) < 8:
        return False
    if not any(ch.isdigit() for ch in pw):
        return False
    if not any(ch.isupper() for ch in pw):
        return False
    if pw.lower() in COMMON_PASSWORDS:
        return False
    return True
