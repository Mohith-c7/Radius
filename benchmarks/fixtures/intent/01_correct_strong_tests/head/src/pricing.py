"""Tiny pricing helpers (original fixture code)."""


def line_total(unit_price: float, quantity: int) -> float:
    return round(unit_price * quantity, 2)


def apply_discount(price: float, percent: float) -> float:
    """Reduce price by percent (0..100 inclusive), rounded to 2 decimals."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price * (1 - percent / 100), 2)
