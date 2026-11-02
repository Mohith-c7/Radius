"""Paired comparison of two extractor results on the same PRs (IN-10).

Per PREREGISTRATION 5.4 the comparison unit is the PR: both extractors are
scored on the same resampled PRs in every bootstrap replicate and the
difference ``metric(A) - metric(B)`` gets a percentile interval. An interval
that excludes 0 is reported as such; confirmatory claims still go through the
Holm-adjusted analysis plan, not through this table. Inputs are run records
(``run.json``) so the comparison is exactly reproducible from stored counts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .metrics import compute_metrics
from .stats import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    paired_bootstrap_diff,
    sum_vectors,
)


class CompareError(ValueError):
    """The two results cannot be compared."""


def _pick(record: Mapping[str, Any], extractor_id: str | None, label: str) -> str:
    extractors = record["extractors"]
    if extractor_id is None:
        if len(extractors) != 1:
            raise CompareError(
                f"run {label} has {len(extractors)} extractors; choose one with "
                f"--{label.lower()}-extractor ({', '.join(sorted(extractors))})"
            )
        return next(iter(extractors))
    if extractor_id not in extractors:
        raise CompareError(
            f"run {label} has no extractor {extractor_id!r} "
            f"(available: {', '.join(sorted(extractors))})"
        )
    return extractor_id


def compare_runs(
    run_a: Mapping[str, Any],
    run_b: Mapping[str, Any],
    *,
    extractor_a: str | None = None,
    extractor_b: str | None = None,
    resamples: int | None = None,
    seed: int | None = None,
    confidence: float | None = None,
    allow_dataset_mismatch: bool = False,
) -> dict[str, Any]:
    """Paired cluster-bootstrap comparison of one extractor from each run."""
    id_a = _pick(run_a, extractor_a, "A")
    id_b = _pick(run_b, extractor_b, "B")
    man_a, man_b = run_a["manifest"], run_b["manifest"]
    warnings: list[str] = []
    same_dataset = man_a["dataset"]["sha256"] == man_b["dataset"]["sha256"]
    if not same_dataset:
        if not allow_dataset_mismatch:
            raise CompareError(
                "runs use different dataset hashes "
                f"({man_a['dataset']['sha256'][:12]} vs {man_b['dataset']['sha256'][:12]}); "
                "pass --allow-dataset-mismatch to compare the shared PRs anyway"
            )
        warnings.append("dataset hashes differ; only shared PR ids are compared")
    if man_a["config"]["matching"] != man_b["config"]["matching"]:
        warnings.append("matching thresholds differ between the runs")
    cases_a = run_a["extractors"][id_a]["cases"]
    cases_b = run_b["extractors"][id_b]["cases"]
    shared = sorted(set(cases_a) & set(cases_b))
    if not shared:
        raise CompareError("the runs share no PR ids")
    if len(shared) < max(len(cases_a), len(cases_b)):
        warnings.append(
            f"comparing {len(shared)} shared PRs of {len(cases_a)} (A) and {len(cases_b)} (B)"
        )
    resamples = resamples or man_a["config"]["bootstrap"]["resamples"] or DEFAULT_RESAMPLES
    confidence = confidence or man_a["config"]["bootstrap"].get(
        "confidence", DEFAULT_CONFIDENCE
    )
    seed = man_a["seeds"]["bootstrap"] if seed is None else seed
    diffs = paired_bootstrap_diff(
        [cases_a[c]["vector"] for c in shared],
        [cases_b[c]["vector"] for c in shared],
        compute_metrics,
        resamples=resamples,
        seed=seed,
        confidence=confidence,
    )
    point_a = compute_metrics(sum_vectors([cases_a[c]["vector"] for c in shared]))
    point_b = compute_metrics(sum_vectors([cases_b[c]["vector"] for c in shared]))
    rows = {}
    for name, diff in diffs.items():
        rows[name] = {
            **diff.as_dict(),
            "a": point_a.get(name),
            "b": point_b.get(name),
        }
    return {
        "a": {"run_id": man_a["run_id"], "extractor": id_a},
        "b": {"run_id": man_b["run_id"], "extractor": id_b},
        "synthetic": bool(man_a["dataset"]["synthetic"] or man_b["dataset"]["synthetic"]),
        "n_cases": len(shared),
        "resamples": resamples,
        "confidence": confidence,
        "seed": seed,
        "warnings": warnings,
        "differences": rows,
    }
