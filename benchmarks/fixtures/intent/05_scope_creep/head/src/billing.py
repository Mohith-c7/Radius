"""Billing helpers (original fixture code)."""
from decimal import ROUND_HALF_UP, Decimal


def round_money(amount: float) -> float:
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP))
