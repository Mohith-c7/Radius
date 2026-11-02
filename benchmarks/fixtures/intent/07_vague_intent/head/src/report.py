"""Report helpers (original fixture code)."""
from collections import defaultdict


def summarize(rows):
    """Return (name, total) pairs sorted by name."""
    totals = defaultdict(int)
    for name, amount in rows:
        totals[name] += amount
    return sorted(totals.items())


def top(rows, n=3):
    """Return the n largest (name, total) pairs."""
    ranked = sorted(summarize(rows), key=lambda pair: pair[1], reverse=True)
    return ranked[:n]
