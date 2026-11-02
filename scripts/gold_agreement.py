"""Inter-annotator agreement and adjudication skeletons for the IN-09 gold set.

Stdlib only. Subcommands::

    python scripts/gold_agreement.py compare  --gold-dir DIR [--a ID --b ID]
        [--iou 0.5] [--bootstrap 2000] [--seed N] [--prs FILE] [--out report.json]
        [--md report.md] [--include-incomplete] [--allow-synthetic]
    python scripts/gold_agreement.py skeleton --gold-dir DIR --adjudicator ID
        [--a ID --b ID] [--prs FILE] [--force] [--allow-synthetic]

Definitions (see docs/research/annotation/GUIDELINES.md section 7):

* Span matching: two explicit criteria in the same source match when their
  character IoU is >= ``--iou`` (default 0.5, the preregistered match rule).
  Matching is one-to-one and greedy by (IoU desc, text similarity desc, order).
* Span F1 between annotators: ``2*matched / (n_a + n_b)``; symmetric, and equal
  to precision, recall and F1 of either annotator against the other.
* Criterion-presence kappa (the preregistered "is this an atomic criterion"
  agreement): the units are the non-blank lines of every stored source of the
  PR; an annotator labels a unit 1 when any of its explicit spans overlaps a
  non-whitespace character of the unit. Cohen's kappa on the pooled units.
* Testability kappa: Cohen's kappa on the testability labels of matched pairs.
  Krippendorff's alpha (nominal) on the same pairs.
* Implicit criteria have no span and are counted, not matched.
* CIs: percentile bootstrap over PRs (cluster resampling), seeded.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import statistics
import sys
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402

DEFAULT_IOU = 0.5
KAPPA_GATE = 0.60  # PREREGISTRATION 5.4

# --------------------------------------------------------------------------
# Agreement statistics
# --------------------------------------------------------------------------


def cohen_kappa(pairs: list[tuple]) -> dict:
    """Cohen's kappa for two raters over ``pairs`` of labels.

    Returns ``{"kappa", "po", "pe", "n"}``; ``kappa`` is ``None`` when it is
    undefined (no items, or chance agreement 1 because both raters used one
    single category).
    """
    n = len(pairs)
    if n == 0:
        return {"kappa": None, "po": None, "pe": None, "n": 0}
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    kappa = None if math.isclose(pe, 1.0) else (po - pe) / (1 - pe)
    return {"kappa": kappa, "po": po, "pe": pe, "n": n}


def krippendorff_alpha_nominal(units: list[list]) -> dict:
    """Krippendorff's alpha for nominal data; ``units`` lists each unit's values.

    Missing values are simply omitted from a unit; units with fewer than two
    values are ignored. alpha = 1 - (n - 1) * sum_{c!=k} o_ck / sum_{c!=k} n_c n_k
    with the usual coincidence matrix (each ordered pair of values in a unit
    contributes 1 / (m_u - 1)). ``alpha`` is ``None`` when undefined.
    """
    coincidence: Counter = Counter()
    for values in units:
        m = len(values)
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i != j:
                    coincidence[(values[i], values[j])] += 1.0 / (m - 1)
    totals: Counter = Counter()
    for (c, _k), v in coincidence.items():
        totals[c] += v
    n = sum(totals.values())
    if n <= 1:
        return {"alpha": None, "n_values": n, "n_units": 0}
    observed = sum(v for (c, k), v in coincidence.items() if c != k)
    expected = sum(totals[c] * totals[k] for c in totals for k in totals if c != k)
    n_units = sum(1 for u in units if len(u) >= 2)
    if expected == 0:
        return {"alpha": None, "n_values": n, "n_units": n_units}
    return {"alpha": 1 - (n - 1) * observed / expected, "n_values": n, "n_units": n_units}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", (text or "").lower()))


def text_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def match_criteria(
    a_items: list[dict], b_items: list[dict], threshold: float = DEFAULT_IOU
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """One-to-one greedy matching of explicit criteria by span IoU.

    Returns ``(pairs, unmatched_a_indexes, unmatched_b_indexes)`` where pairs
    are ``(i, j, iou)``. A pair needs ``iou >= threshold``.
    """
    cands = []
    for i, a in enumerate(a_items):
        for j, b in enumerate(b_items):
            iou = gl.span_iou(a["span"], b["span"])
            if iou > 0 and iou >= threshold:
                cands.append((-iou, -text_similarity(a["text"], b["text"]), i, j))
    cands.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs = []
    for neg_iou, _sim, i, j in cands:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j, -neg_iou))
    pairs.sort()
    return (
        pairs,
        [i for i in range(len(a_items)) if i not in used_a],
        [j for j in range(len(b_items)) if j not in used_b],
    )


def _unit_labels(src: dict, a_spans: list[dict], b_spans: list[dict]) -> list[tuple[int, int]]:
    """(label_a, label_b) for every non-blank line of every source."""
    out = []
    for s in src["sources"]:
        text = s["text"]
        if text is None:
            continue
        pos = 0
        for line in text.split("\n"):
            start, end = pos, pos + len(line)
            pos = end + 1
            if not line.strip():
                continue
            visible = [start + k for k, ch in enumerate(line) if not ch.isspace()]
            lab = []
            for spans in (a_spans, b_spans):
                hit = any(
                    sp["source_id"] == s["source_id"]
                    and any(sp["start"] <= p < sp["end"] for p in visible)
                    for sp in spans
                )
                lab.append(1 if hit else 0)
            out.append((lab[0], lab[1]))
    return out


# --------------------------------------------------------------------------
# Per-PR comparison
# --------------------------------------------------------------------------


def compare_pr(src: dict, a: dict, b: dict, threshold: float = DEFAULT_IOU) -> dict:
    """Compare two annotator documents of one PR."""
    kinds = {s["source_id"]: s["kind"] for s in src["sources"]}
    ea = [c for c in a["criteria"] if c["explicit"]]
    eb = [c for c in b["criteria"] if c["explicit"]]
    pairs, ua, ub = match_criteria(ea, eb, threshold)
    matched = []
    for i, j, iou in pairs:
        matched.append(
            {
                "a": ea[i],
                "b": eb[j],
                "iou": iou,
                "kind": kinds.get(ea[i]["span"]["source_id"], "unknown"),
                "exact": ea[i]["span"] == eb[j]["span"],
            }
        )
    # Overlapping but below threshold: boundary disagreements worth a look.
    boundary = []
    for i in ua:
        for j in ub:
            iou = gl.span_iou(ea[i]["span"], eb[j]["span"])
            if iou > 0:
                boundary.append({"a": ea[i], "b": eb[j], "iou": iou})
    units = _unit_labels(src, [c["span"] for c in ea], [c["span"] for c in eb])
    return {
        "pr_id": src["pr_id"],
        "annotators": [a["annotator_id"], b["annotator_id"]],
        "kinds": kinds,
        "n_a": len(ea),
        "n_b": len(eb),
        "matched": matched,
        "only_a": [ea[i] for i in ua],
        "only_b": [eb[j] for j in ub],
        "boundary": boundary,
        "implicit_a": [c for c in a["criteria"] if not c["explicit"]],
        "implicit_b": [c for c in b["criteria"] if not c["explicit"]],
        "units": units,
        "well_specified": (a["well_specified"], b["well_specified"]),
        "author_type": src["pr"].get("author_type", "unknown"),
        "timing": (a["timing"]["active_seconds"], b["timing"]["active_seconds"]),
    }


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _f1(comps: list[dict], kind: str | None = None) -> float | None:
    m = na = nb = 0
    for c in comps:
        if kind is None:
            m += len(c["matched"])
            na += c["n_a"]
            nb += c["n_b"]
        else:
            m += sum(1 for x in c["matched"] if x["kind"] == kind)
            na += sum(1 for x in c["matched"] if x["kind"] == kind) + sum(
                1 for x in c["only_a"] if c["kinds"].get(x["span"]["source_id"]) == kind
            )
            nb += sum(1 for x in c["matched"] if x["kind"] == kind) + sum(
                1 for x in c["only_b"] if c["kinds"].get(x["span"]["source_id"]) == kind
            )
    return None if na + nb == 0 else 2 * m / (na + nb)


def _test_pairs(comps: list[dict], kind: str | None = None) -> list[tuple]:
    return [
        (m["a"]["testability"], m["b"]["testability"])
        for c in comps
        for m in c["matched"]
        if kind is None or m["kind"] == kind
    ]


def _unit_pairs(comps: list[dict]) -> list[tuple]:
    return [u for c in comps for u in c["units"]]


def _metrics(comps: list[dict], kind: str | None = None) -> dict:
    tp = _test_pairs(comps, kind)
    out = {
        "span_f1": _f1(comps, kind),
        "testability_kappa": cohen_kappa(tp),
        "testability_alpha": krippendorff_alpha_nominal([[a, b] for a, b in tp]),
        "n_matched": len(tp),
    }
    if kind is None:
        out["presence_kappa"] = cohen_kappa(_unit_pairs(comps))
        out["n_explicit_a"] = sum(c["n_a"] for c in comps)
        out["n_explicit_b"] = sum(c["n_b"] for c in comps)
        out["n_implicit_a"] = sum(len(c["implicit_a"]) for c in comps)
        out["n_implicit_b"] = sum(len(c["implicit_b"]) for c in comps)
        out["exact_span_share"] = (
            sum(1 for c in comps for m in c["matched"] if m["exact"])
            / max(1, sum(len(c["matched"]) for c in comps))
        )
    else:
        out["n_a"] = sum(
            1 for c in comps for m in c["matched"] if m["kind"] == kind
        ) + sum(
            1 for c in comps for x in c["only_a"] if c["kinds"].get(x["span"]["source_id"]) == kind
        )
        out["n_b"] = sum(
            1 for c in comps for m in c["matched"] if m["kind"] == kind
        ) + sum(
            1 for c in comps for x in c["only_b"] if c["kinds"].get(x["span"]["source_id"]) == kind
        )
    return out


def bootstrap_ci(
    comps: list[dict], fn, n_boot: int, seed: int, level: float = 0.95
) -> list[float] | None:
    """Percentile CI of ``fn(list_of_pr_comparisons)`` resampling PRs."""
    if n_boot <= 0 or len(comps) < 2:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        sample = [comps[rng.randrange(len(comps))] for _ in comps]
        v = fn(sample)
        if v is not None:
            vals.append(v)
    if len(vals) < max(10, n_boot // 10):
        return None
    vals.sort()
    lo = vals[int((1 - level) / 2 * (len(vals) - 1))]
    hi = vals[int((1 + level) / 2 * (len(vals) - 1))]
    return [lo, hi]


def build_report(
    comps: list[dict],
    *,
    threshold: float = DEFAULT_IOU,
    n_boot: int = 2000,
    seed: int = 20261102,
    synthetic: bool = False,
) -> dict:
    kinds = sorted({k for c in comps for k in c["kinds"].values()})
    overall = _metrics(comps)
    overall["ci95"] = {
        "span_f1": bootstrap_ci(comps, lambda cs: _f1(cs), n_boot, seed),
        "presence_kappa": bootstrap_ci(
            comps, lambda cs: cohen_kappa(_unit_pairs(cs))["kappa"], n_boot, seed
        ),
        "testability_kappa": bootstrap_ci(
            comps, lambda cs: cohen_kappa(_test_pairs(cs))["kappa"], n_boot, seed
        ),
    }
    ws_pairs = [c["well_specified"] for c in comps if None not in c["well_specified"]]
    times: dict[str, list[float]] = {}
    for c in comps:
        for aid, secs in zip(c["annotators"], c["timing"], strict=True):
            times.setdefault(aid, []).append(secs)
    pres = overall["presence_kappa"]["kappa"]
    tk = overall["testability_kappa"]["kappa"]
    report = {
        "synthetic": synthetic,
        "iou_threshold": threshold,
        "bootstrap": {"resamples": n_boot, "seed": seed, "unit": "pr"},
        "n_prs": len(comps),
        "prs": [c["pr_id"] for c in comps],
        "annotator_pairs": sorted({tuple(c["annotators"]) for c in comps}),
        "overall": overall,
        "by_source_kind": {k: _metrics(comps, k) for k in kinds},
        "by_author_type": {
            t: {
                "n_prs": len(sub),
                "span_f1": _f1(sub),
                "presence_kappa": cohen_kappa(_unit_pairs(sub)),
            }
            for t in sorted({c["author_type"] for c in comps})
            for sub in [[c for c in comps if c["author_type"] == t]]
        },
        "well_specified": cohen_kappa(ws_pairs),
        "timing_seconds_per_pr": {
            aid: {
                "n": len(v),
                "median": statistics.median(v) if v else None,
                "mean": statistics.fmean(v) if v else None,
                "total_hours": sum(v) / 3600,
            }
            for aid, v in sorted(times.items())
        },
        "gate": {
            "threshold": KAPPA_GATE,
            "presence_kappa": pres,
            "testability_kappa": tk,
            "presence_pass": None if pres is None else pres >= KAPPA_GATE,
            "testability_pass": None if tk is None else tk >= KAPPA_GATE,
            "note": (
                "PREREGISTRATION 5.4: kappa < 0.60 on the 30-PR pilot triggers guideline "
                "revision and re-annotation; after one revision round still < 0.60 means RQ1 is "
                "reported as 'annotation reliability insufficient'."
            ),
        },
        "disagreements": disagreements(comps),
    }
    return report


def _brief(c: dict) -> dict:
    return {
        "id": c["id"],
        "span": c.get("span"),
        "text": c.get("text"),
        "testability": c.get("testability"),
    }


def disagreements(comps: list[dict]) -> list[dict]:
    """Items to adjudicate, deterministic order."""
    out = []
    for c in comps:
        pid = c["pr_id"]
        for m in c["matched"]:
            if m["a"]["testability"] != m["b"]["testability"]:
                out.append({"pr_id": pid, "type": "testability_conflict", "iou": m["iou"],
                            "a": _brief(m["a"]), "b": _brief(m["b"])})
            elif not m["exact"]:
                out.append({"pr_id": pid, "type": "span_boundary", "iou": m["iou"],
                            "a": _brief(m["a"]), "b": _brief(m["b"])})
        for x in c["boundary"]:
            out.append({"pr_id": pid, "type": "overlap_below_threshold", "iou": x["iou"],
                        "a": _brief(x["a"]), "b": _brief(x["b"])})
        bounded_a = {x["a"]["id"] for x in c["boundary"]}
        bounded_b = {x["b"]["id"] for x in c["boundary"]}
        for x in c["only_a"]:
            if x["id"] not in bounded_a:
                out.append({"pr_id": pid, "type": "only_a", "a": _brief(x), "b": None})
        for x in c["only_b"]:
            if x["id"] not in bounded_b:
                out.append({"pr_id": pid, "type": "only_b", "a": None, "b": _brief(x)})
        for x in c["implicit_a"]:
            out.append({"pr_id": pid, "type": "implicit_a", "a": _brief(x), "b": None})
        for x in c["implicit_b"]:
            out.append({"pr_id": pid, "type": "implicit_b", "a": None, "b": _brief(x)})
        wa, wb = c["well_specified"]
        if wa != wb:
            out.append({"pr_id": pid, "type": "well_specified_conflict",
                        "a": {"value": wa}, "b": {"value": wb}})
    return out


def _fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def report_markdown(rep: dict) -> str:
    o = rep["overall"]
    ci = o["ci95"]

    def with_ci(val, key):
        c = ci.get(key)
        return _fmt(val) + (f" (95% CI {_fmt(c[0])} to {_fmt(c[1])})" if c else "")

    lines = ["# Inter-annotator agreement report", ""]
    if rep["synthetic"]:
        lines += ["**SYNTHETIC DATA: generated by scripts/gold_synthetic.py, not real gold.**", ""]
    lines += [
        f"- PRs compared: {rep['n_prs']}; IoU threshold {rep['iou_threshold']}; "
        f"bootstrap {rep['bootstrap']['resamples']} resamples over PRs (seed {rep['bootstrap']['seed']})",
        f"- Explicit criteria: A {o['n_explicit_a']}, B {o['n_explicit_b']}, matched {o['n_matched']}; "
        f"implicit: A {o['n_implicit_a']}, B {o['n_implicit_b']}",
        f"- Span F1 (A vs B): {with_ci(o['span_f1'], 'span_f1')}; exact-boundary share of matches: "
        f"{_fmt(o['exact_span_share'])}",
        f"- Criterion-presence kappa (line units, n={o['presence_kappa']['n']}): "
        f"{with_ci(o['presence_kappa']['kappa'], 'presence_kappa')}",
        f"- Testability kappa (matched pairs, n={o['testability_kappa']['n']}): "
        f"{with_ci(o['testability_kappa']['kappa'], 'testability_kappa')}; "
        f"Krippendorff alpha (nominal): {_fmt(o['testability_alpha']['alpha'])}",
        f"- well-specified flag kappa: {_fmt(rep['well_specified']['kappa'])} "
        f"(n={rep['well_specified']['n']})",
        "",
        "## Gate (preregistered kappa >= 0.60)",
        f"- presence: {rep['gate']['presence_pass']}; testability: {rep['gate']['testability_pass']}",
        f"- {rep['gate']['note']}",
        "",
        "## By source kind",
        "",
        "| kind | n_a | n_b | matched | span F1 | testability kappa | alpha |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, m in rep["by_source_kind"].items():
        lines.append(
            f"| {k} | {m['n_a']} | {m['n_b']} | {m['n_matched']} | {_fmt(m['span_f1'])} | "
            f"{_fmt(m['testability_kappa']['kappa'])} | {_fmt(m['testability_alpha']['alpha'])} |"
        )
    lines += ["", "## By author type", "", "| type | PRs | span F1 | presence kappa |", "|---|---|---|---|"]
    for t, m in rep["by_author_type"].items():
        lines.append(
            f"| {t} | {m['n_prs']} | {_fmt(m['span_f1'])} | {_fmt(m['presence_kappa']['kappa'])} |"
        )
    lines += ["", "## Annotation time (active seconds per PR)", ""]
    for aid, t in rep["timing_seconds_per_pr"].items():
        lines.append(
            f"- {aid}: n={t['n']}, median {_fmt(t['median'], 0)} s, mean {_fmt(t['mean'], 0)} s, "
            f"total {_fmt(t['total_hours'], 2)} h"
        )
    counts = Counter(d["type"] for d in rep["disagreements"])
    lines += ["", f"## Items for adjudication ({len(rep['disagreements'])})", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(counts.items())]
    lines += ["", "| PR | type | IoU | A | B |", "|---|---|---|---|---|"]
    for d in rep["disagreements"]:
        def cell(x):
            if x is None:
                return "-"
            if "value" in x:
                return str(x["value"])
            t = (x.get("text") or "").replace("|", "\\|").replace("\n", " ")
            sp = x.get("span") or {}
            return f"{x['id']} {x.get('testability')} [{sp.get('start')},{sp.get('end')}) {t[:60]}"

        lines.append(
            f"| {d['pr_id']} | {d['type']} | {_fmt(d.get('iou'), 2)} | {cell(d['a'])} | {cell(d['b'])} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Adjudication skeleton
# --------------------------------------------------------------------------


def build_skeleton(
    src: dict, a: dict, b: dict, comp: dict, adjudicator: str, *, now: str
) -> dict:
    """An ``adjudicated.json`` with agreed items prefilled and the rest pending."""
    gl.check_annotator_id(adjudicator)
    aid, bid = a["annotator_id"], b["annotator_id"]
    if adjudicator in (aid, bid):
        raise gl.GoldError("the adjudicator must be a third person, not one of the annotators")
    items: list[dict] = []

    def add(**kw):
        items.append({"explicit": True, "text": None, "testability": None, **kw})

    for m in comp["matched"]:
        ca, cb = m["a"], m["b"]
        if m["exact"] and ca["testability"] == cb["testability"]:
            add(
                resolution="agreed",
                span=ca["span"],
                text=ca["text"],
                testability=ca["testability"],
                origin={aid: ca["id"], bid: cb["id"]},
                reasons=[],
            )
        else:
            reasons = []
            if not m["exact"]:
                reasons.append("span_boundary")
            if ca["testability"] != cb["testability"]:
                reasons.append("testability_conflict")
            add(
                resolution="pending",
                span=None,
                origin={aid: ca["id"], bid: cb["id"]},
                reasons=reasons,
                options={aid: ca, bid: cb},
            )
    bounded_a = {x["a"]["id"] for x in comp["boundary"]}
    bounded_b = {x["b"]["id"] for x in comp["boundary"]}
    for x in comp["boundary"]:
        add(
            resolution="pending",
            span=None,
            origin={aid: x["a"]["id"], bid: x["b"]["id"]},
            reasons=["overlap_below_threshold"],
            options={aid: x["a"], bid: x["b"]},
        )
    for x in comp["only_a"]:
        if x["id"] not in bounded_a:
            add(resolution="pending", span=None, origin={aid: x["id"]},
                reasons=["only_" + aid], options={aid: x})
    for x in comp["only_b"]:
        if x["id"] not in bounded_b:
            add(resolution="pending", span=None, origin={bid: x["id"]},
                reasons=["only_" + bid], options={bid: x})
    for who, lst in ((aid, comp["implicit_a"]), (bid, comp["implicit_b"])):
        for x in lst:
            add(resolution="pending", explicit=False, span=None, origin={who: x["id"]},
                reasons=["implicit_" + who], options={who: x})

    def order(it):
        sp = it.get("span")
        if sp is None:
            first = next(iter(it["options"].values()))
            sp = first.get("span") or {"source_id": "~", "start": 0}
        return (sp["source_id"], sp["start"], it["resolution"] == "pending")

    items.sort(key=order)
    for n, it in enumerate(items, 1):
        it["id"] = f"a{n}"
    wa, wb = a["well_specified"], b["well_specified"]
    complete = not any(i["resolution"] == "pending" for i in items) and wa == wb and wa is not None
    return {
        "schema_version": gl.SCHEMA_VERSION,
        "kind": "adjudicated",
        "pr_id": src["pr_id"],
        "sources_digest": src["sources_digest"],
        "adjudicator_id": adjudicator,
        "annotators": [aid, bid],
        "status": "complete" if complete else "skeleton",
        "well_specified": wa if wa == wb else None,
        "well_specified_set_at": None,
        "well_specified_conflict": [wa, wb] if wa != wb else [],
        "no_recoverable_intent": bool(a["no_recoverable_intent"] and b["no_recoverable_intent"]),
        "criteria": items,
        "links": [],
        "timing": {"active_seconds": 0, "sessions": 0, "first_opened_at": now},
        "tool": {"name": "gold_agreement", "version": gl.TOOL_VERSION},
        "guidelines_version": gl.GUIDELINES_VERSION,
        "synthetic": bool(src.get("synthetic")),
    }


# --------------------------------------------------------------------------
# Loading and CLI
# --------------------------------------------------------------------------


def collect(
    gold_dir: Path,
    *,
    a_id: str | None = None,
    b_id: str | None = None,
    pr_ids: list[str] | None = None,
    include_incomplete: bool = False,
    allow_synthetic: bool = False,
    threshold: float = DEFAULT_IOU,
) -> tuple[list[dict], dict, list[dict]]:
    """Return ``(comparisons, {pr_id: (src, a, b)}, skipped)``."""
    comps, docs, skipped = [], {}, []
    for pid in pr_ids if pr_ids is not None else gl.list_pr_ids(gold_dir):
        src, anns, _adj = gl.load_pr(gold_dir, pid)
        if src.get("synthetic") and not allow_synthetic:
            raise gl.GoldError(f"{pid} is synthetic; pass --allow-synthetic to use it")
        if a_id and b_id:
            ids = [a_id, b_id]
        else:
            ids = sorted(anns)
        if len(ids) != 2 or any(i not in anns for i in ids):
            skipped.append({"pr_id": pid, "reason": f"needs exactly two annotators, have {sorted(anns)}"})
            continue
        a, b = anns[ids[0]], anns[ids[1]]
        if not include_incomplete and (a["status"] != "complete" or b["status"] != "complete"):
            skipped.append({"pr_id": pid, "reason": "annotation not complete"})
            continue
        for doc in (a, b):
            errs, _ = gl.validate_annotation_doc(doc, src)
            if errs:
                raise gl.GoldError(f"{pid}/{doc['annotator_id']}: {errs[0]}")
        comps.append(compare_pr(src, a, b, threshold))
        docs[pid] = (src, a, b)
    return comps, docs, skipped


def _read_prs(path: str | None) -> list[str] | None:
    if not path:
        return None
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("compare", "skeleton"):
        p = sub.add_parser(name)
        p.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
        p.add_argument("--a")
        p.add_argument("--b")
        p.add_argument("--prs", help="file with one pr id per line")
        p.add_argument("--iou", type=float, default=DEFAULT_IOU)
        p.add_argument("--allow-synthetic", action="store_true")
        p.add_argument("--include-incomplete", action="store_true")
    c = sub.choices["compare"]
    c.add_argument("--bootstrap", type=int, default=2000)
    c.add_argument("--seed", type=int, default=20261102)
    c.add_argument("--out")
    c.add_argument("--md")
    s = sub.choices["skeleton"]
    s.add_argument("--adjudicator", required=True)
    s.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    gold_dir = Path(args.gold_dir)
    try:
        comps, docs, skipped = collect(
            gold_dir, a_id=args.a, b_id=args.b, pr_ids=_read_prs(args.prs),
            include_incomplete=args.include_incomplete or args.cmd == "skeleton",
            allow_synthetic=args.allow_synthetic, threshold=args.iou,
        )
        if args.cmd == "compare":
            synth = any(d[0].get("synthetic") for d in docs.values())
            rep = build_report(comps, threshold=args.iou, n_boot=args.bootstrap,
                               seed=args.seed, synthetic=synth)
            rep["skipped"] = skipped
            if args.out:
                gl.write_json_atomic(Path(args.out), rep)
            md = report_markdown(rep)
            if args.md:
                Path(args.md).write_text(md, encoding="utf-8", newline="\n")
            print(md)
            return 0
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        written = 0
        for comp in comps:
            src, a, b = docs[comp["pr_id"]]
            path = gl.pr_dir(gold_dir, comp["pr_id"]) / "adjudicated.json"
            if path.exists() and not args.force:
                print(f"skip {comp['pr_id']}: adjudicated.json exists (use --force)")
                continue
            doc = build_skeleton(src, a, b, comp, args.adjudicator, now=now)
            gl.write_json_atomic(path, doc)
            written += 1
        print(f"wrote {written} skeleton(s); skipped {len(skipped)}")
        return 0
    except gl.GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
