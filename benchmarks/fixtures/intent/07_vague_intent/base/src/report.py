"""Report helpers (original fixture code)."""


def summarize(rows):
    """Return (name, total) pairs sorted by name."""
    totals = {}
    for name, amount in rows:
        totals[name] = totals.get(name, 0) + amount
    return sorted(totals.items())
