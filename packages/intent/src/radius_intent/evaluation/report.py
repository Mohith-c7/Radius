"""Render run records and comparisons as markdown / JSON (pure functions)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .metrics import MODES, RATED_LABELS, UNRATED

SYNTHETIC_BANNER = (
    "> **SYNTHETIC — not a research result.** This run used synthetic or "
    "fixture-derived data and exists only to exercise the harness."
)
_MODE_TITLE = {
    "iou": "span IoU (primary)",
    "text_exact": "normalized text equality",
    "text_fuzzy": "token Jaccard (fuzzy)",
}


def fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def fmt_ci(metric: Mapping[str, Any] | None, digits: int = 3) -> str:
    """``0.750 [0.600, 0.900]`` or ``n/a``."""
    if not metric or metric.get("estimate") is None:
        return "n/a"
    est = fmt(metric["estimate"], digits)
    if metric.get("low") is None or metric.get("high") is None:
        return est
    return f"{est} [{fmt(metric['low'], digits)}, {fmt(metric['high'], digits)}]"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return [*lines, ""]


def _m(entry: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    return entry["metrics"].get(name)


def _prf_row(entry: Mapping[str, Any], mode: str, group: str, label: str) -> list[str]:
    pre = f"{mode}.{group}."
    counts = entry["groups"].get(group, {}).get(mode, {})
    return [
        label,
        fmt_ci(_m(entry, pre + "precision")),
        fmt_ci(_m(entry, pre + "recall")),
        fmt_ci(_m(entry, pre + "f1")),
        fmt_ci(_m(entry, pre + "macro_f1")),
        f"{counts.get('tp', 0)}/{counts.get('pred', 0)}/{counts.get('gold', 0)}",
    ]


_PRF_HEADERS = ("", "Precision", "Recall", "F1 (micro)", "F1 (per-PR macro)", "tp/pred/gold")


def render_markdown(record: Mapping[str, Any]) -> str:
    """Full report of a run record."""
    man = record["manifest"]
    ds = man["dataset"]
    cfg = man["config"]
    lines = [f"# Intent extraction metrics: {man['run_id']}", ""]
    if ds["synthetic"]:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        "## Run",
        "",
        f"- Dataset: `{ds['name']}` v{ds['version']} ({ds['split']}), "
        f"{ds['n_cases']} PRs, {ds['n_gold_criteria']} gold criteria, "
        f"{ds['n_cases_without_gold']} PRs without gold",
        f"- Dataset sha256: `{ds['sha256']}`",
        f"- Config sha256: `{man['config_sha256']}`",
        f"- Matching: IoU >= {cfg['matching']['iou_threshold']}, "
        f"fuzzy text Jaccard >= {cfg['matching']['text_threshold']}",
        f"- Bootstrap: {cfg['bootstrap']['resamples']} cluster (PR) resamples, "
        f"{cfg['bootstrap']['confidence']:.0%} percentile intervals, "
        f"seed {man['seeds']['bootstrap']}",
        f"- Git: `{(man.get('git') or {}).get('sha', 'unknown')}`"
        + (" (dirty)" if (man.get("git") or {}).get("dirty") else ""),
        f"- Harness: `{man['harness_version']}`; created {man['created_at']}",
        "",
    ]
    if ds["warnings"] or ds["notes"]:
        lines += ["### Dataset notes", ""]
        lines += [f"- {n}" for n in [*ds["notes"], *ds["warnings"]]]
        lines.append("")
    extractors = record["extractors"]

    lines += ["## Summary (primary: span IoU, micro over PRs, 95% CI)", ""]
    rows = []
    for eid, e in extractors.items():
        rows.append(
            [
                f"`{eid}`",
                fmt_ci(_m(e, "iou.all.precision")),
                fmt_ci(_m(e, "iou.all.recall")),
                fmt_ci(_m(e, "iou.all.f1")),
                fmt_ci(_m(e, "text_fuzzy.all.f1")),
                fmt_ci(_m(e, "tx.accuracy")),
                fmt_ci(_m(e, "abstention.empty_prediction_rate")),
            ]
        )
    lines += _table(
        ["Extractor", "Precision", "Recall", "F1", "F1 (fuzzy text)", "Testability acc.", "Empty-PR rate"],
        rows,
    )

    for eid, e in extractors.items():
        lines += _extractor_section(eid, e)

    lines += ["## Reproducibility", ""]
    lines += [
        "| Extractor | Versions | Seconds | LLM calls | Tokens in/out | Errors |",
        "|---|---|---|---|---|---|",
    ]
    for eid, e in extractors.items():
        versions = ", ".join(
            f"{k}={v}" for k, v in sorted(e["describe"].items()) if k != "kind"
        )
        u = e["usage"]
        cost = f" (~${u['estimated_cost_usd']})" if "estimated_cost_usd" in u else ""
        lines.append(
            f"| `{eid}` | {versions or 'n/a'} | {e['timing_s']} | {u['llm_calls']} "
            f"(+{u['cache_hits']} cached) | {u['input_tokens']}/{u['output_tokens']}{cost} "
            f"| {len(e['errors'])} |"
        )
    lines.append("")
    if ds["synthetic"]:
        lines += [SYNTHETIC_BANNER, ""]
    return "\n".join(lines)


def _extractor_section(eid: str, e: Mapping[str, Any]) -> list[str]:
    lines = [f"## Extractor `{eid}` ({e['kind']})", ""]
    lines += ["### Matching modes (all PRs)", ""]
    lines += _table(
        _PRF_HEADERS,
        [_prf_row(e, mode, "all", _MODE_TITLE[mode]) for mode in MODES],
    )
    groups = list(e["groups"])
    kinds = [g for g in groups if g.startswith("kind:")]
    if kinds:
        lines += ["### Per source type (span IoU)", ""]
        lines += _table(
            ["Source type", *_PRF_HEADERS[1:]],
            [_prf_row(e, "iou", g, g.removeprefix("kind:")) for g in kinds],
        )
    slices = [g for g in groups if g in ("well_specified", "not_well_specified")]
    slices += [g for g in groups if g.startswith("author:")]
    if slices:
        lines += ["### Per PR slice (span IoU)", ""]
        lines += _table(
            ["Slice", *_PRF_HEADERS[1:]], [_prf_row(e, "iou", g, g) for g in slices]
        )
    lines += ["### Testability (matched criteria with a gold label)", ""]
    n = (_m(e, "tx.n") or {}).get("estimate") or 0
    if not n:
        lines += ["No matched criterion carries a gold testability label.", ""]
    else:
        lines += _table(
            ["Metric", "Value [95% CI]"],
            [
                ["n", str(int(n))],
                ["accuracy", fmt_ci(_m(e, "tx.accuracy"))],
                ["macro-F1", fmt_ci(_m(e, "tx.macro_f1"))],
                ["Cohen's kappa", fmt_ci(_m(e, "tx.kappa"))],
                ["abstained (unrated)", fmt_ci(_m(e, "tx.abstain_rate"))],
            ],
        )
        lines += _confusion_table(e["confusion"])
    lines += ["### Abstention, coverage and PRs without gold", ""]
    lines += _table(
        ["Metric", "Value [95% CI]"],
        [
            ["PRs with no predicted criterion", fmt_ci(_m(e, "abstention.empty_prediction_rate"))],
            ["PRs with gold: any gold criterion matched", fmt_ci(_m(e, "coverage.any_hit_rate"))],
            ["share of PRs without gold", fmt_ci(_m(e, "nogold.share"))],
            ["PRs without gold with >= 1 prediction (false-positive rate)", fmt_ci(_m(e, "nogold.fp_rate"))],
            ["mean predictions on PRs without gold", fmt_ci(_m(e, "nogold.mean_predictions"))],
            ["predictions left unrated", fmt_ci(_m(e, "testability.unrated_pred_rate"))],
            ["mean IoU of matched spans", fmt_ci(_m(e, "span.mean_iou"))],
            ["matched spans with exact boundaries", fmt_ci(_m(e, "span.exact_rate"))],
        ],
    )
    if e["errors"]:
        lines += ["### Extractor errors", ""]
        lines += [f"- `{x['case_id']}`: {x['error']}" for x in e["errors"]]
        lines.append("")
    return lines


def _confusion_table(confusion: Mapping[str, Mapping[str, int]]) -> list[str]:
    cols = [*RATED_LABELS, UNRATED]
    rows = []
    for gold in RATED_LABELS:
        row = confusion.get(gold, {})
        if not row:
            continue
        rows.append([f"**{gold}**", *[str(row.get(c, 0)) for c in cols]])
    if not rows:
        return []
    return ["Confusion matrix (rows: gold, columns: system)", "", *_table(["gold \\ system", *cols], rows)]


def render_summary_json(record: Mapping[str, Any]) -> str:
    """Machine-readable report: manifest and metrics, without per-PR vectors."""
    summary = {
        "manifest": record["manifest"],
        "extractors": {
            eid: {k: v for k, v in e.items() if k != "cases"}
            for eid, e in record["extractors"].items()
        },
    }
    return json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


_COMPARE_METRICS = (
    ("iou.all.precision", "precision"),
    ("iou.all.recall", "recall"),
    ("iou.all.f1", "F1 (micro)"),
    ("iou.all.macro_f1", "F1 (per-PR macro)"),
    ("iou.well_specified.f1", "F1, well-specified PRs"),
    ("text_fuzzy.all.f1", "F1 (fuzzy text)"),
    ("tx.accuracy", "testability accuracy"),
    ("tx.kappa", "testability kappa"),
    ("nogold.fp_rate", "false-positive rate on PRs without gold"),
)


def render_compare_markdown(result: Mapping[str, Any]) -> str:
    """Markdown table of the paired differences A - B."""
    a, b = result["a"], result["b"]
    lines = [f"# Paired comparison: `{a['extractor']}` (A) vs `{b['extractor']}` (B)", ""]
    if result["synthetic"]:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"- A: run `{a['run_id']}`; B: run `{b['run_id']}`",
        f"- {result['n_cases']} shared PRs; paired cluster bootstrap, "
        f"{result['resamples']} resamples, {result['confidence']:.0%} percentile "
        f"interval, seed {result['seed']}",
    ]
    lines += [f"- WARNING: {w}" for w in result["warnings"]]
    lines.append("")
    rows = []
    diffs = result["differences"]
    for name, label in _COMPARE_METRICS:
        d = diffs.get(name)
        if d is None:
            continue
        rows.append(
            [
                label,
                fmt(d["a"]),
                fmt(d["b"]),
                fmt_ci(d),
                fmt(d["p_value"], 4),
                "yes" if d["excludes_zero"] else "no",
            ]
        )
    lines += _table(
        ["Metric", "A", "B", "A - B [95% CI]", "bootstrap p (approx.)", "CI excludes 0"],
        rows,
    )
    lines.append(
        "The p-value is the two-sided bootstrap tail share, floored at "
        "1/(resamples+1); it feeds the Holm adjustment of the analysis plan and is "
        "not an exact test."
    )
    lines.append("")
    if result["synthetic"]:
        lines += [SYNTHETIC_BANNER, ""]
    return "\n".join(lines)
