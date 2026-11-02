"""Stock bookkeeping (original fixture code)."""


class OutOfStock(Exception):
    """Raised when more units are requested than are available."""


def reserve(stock: int, qty: int) -> int:
    """Return the stock left after reserving qty units."""
    return stock - qty


def release(stock: int, qty: int) -> int:
    return stock + qty


def stock_value(stock: int, unit_price: float) -> float:
    return stock * unit_price
