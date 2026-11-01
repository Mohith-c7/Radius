"""Metric aggregation for the real-repo benchmark (pure functions)."""
from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def prf(selected: set[str], relevant: set[str]) -> tuple[float | None, float | None]:
    prec = len(selected & relevant) / len(selected) if selected else None
    rec = len(selected & relevant) / len(relevant) if relevant else None
    return prec, rec


def aggregate(rows: list[dict], method: str) -> dict:
    detected = [r for r in rows if r["truth_failing"]]
    caught = [r for r in detected if set(r[method]["failing"])]
    missed = len(detected) - len(caught)
    out = {"n": len(rows), "detected": len(detected), "caught": len(caught), "missed": missed,
           "detection_ci": wilson(len(caught), len(detected))}
    precs, recs, frac, secs = [], [], [], []
    for r in rows:
        sel = set(r[method]["selected"])
        p, rc = prf(sel, set(r["truth_failing"]))
        if p is not None and r["truth_failing"]:
            precs.append(p)
        if rc is not None:
            recs.append(rc)
        frac.append(len(sel) / r["total_test_files"] if r["total_test_files"] else 0.0)
        secs.append(r[method]["seconds"])
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    out.update(precision=mean(precs), recall=mean(recs), fraction=mean(frac), seconds=mean(secs))
    if method == "radius":
        fs = sum(r["radius"]["verdict"] == "verified" for r in detected)
        ab = sum(r["radius"]["verdict"] == "insufficient_evidence" for r in rows)
        out.update(false_safe=fs, false_safe_ci=wilson(fs, len(detected)), abstain=ab,
                   abstain_ci=wilson(ab, len(rows)))
    return out


def classify_miss(row: dict, method: str) -> str | None:
    """Why `method` missed a detected mutant (None if it did not miss)."""
    truth = set(row["truth_failing"])
    res = row[method]
    if not truth or res["failing"]:
        return None
    if method == "radius" and res.get("verdict") == "crashed":
        return "radius crash"
    hit = truth & set(res["selected"])
    base = "isolation/environment" if hit else "selection error"
    if method == "radius" and res.get("verdict") == "insufficient_evidence":
        return f"{base} (abstained)"
    return base
