#!/usr/bin/env python3
"""Criterion -> symbol -> test chain evaluation hook (LK-06).

    python scripts/link_chain_eval.py [--fixtures DIR] [--json] [--out FILE]
                                      [--calibrator ARTIFACT.json] [--bins 10]

For each F-14 fixture (``benchmarks/fixtures/intent/*``) this

1. extracts changed symbols (LK-01), links criteria to symbols (LK-02 pipeline),
2. links symbols to tests with the static and naming linkers (LK-03; the dynamic
   coverage linker needs the sandbox and is NOT run here),
3. builds chains and per-criterion link confidence (LK-06, ``link-chain-v1``) with
   test outcomes taken from the fixture's ``test_outcomes.head``,
4. scores against the hand-labelled ``links`` of ``expected.json``:
   chain Top-1 / Top-3 / MRR (first gold ``(symbol, test)`` pair among the ranked
   chains of a criterion), recall of gold ``(criterion, symbol, test)`` triples
   among all kept chains, and whether criteria with gold symbols but no gold tests
   get confidence 0 ("untested change"),
5. computes reliability metrics (ECE / MCE / Brier / bins) of chain scores and
   criterion confidences against gold labels (a chain is positive when it is a
   gold triple; a criterion is positive when it has at least one gold test).

THE NUMBERS ARE A FIXTURE SANITY CHECK, NOT A RESEARCH RESULT. Eight tiny
hand-written PRs say nothing about generalisation and the reliability figures are
only a demonstration that the harness runs; no calibration claim is made. RQ1
numbers come from the LK-07 gold set. By default scores are
``link_confidence_uncalibrated``; ``--calibrator`` applies a fitted artifact (and
then reports metrics on the calibrated values, in-sample on these fixtures).

Needs no network and no sandbox. Run with PYTHONPATH as in CI or let this script
add ``packages/*/src``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _pkg in ("linking", "testing", "graph", "analysis", "parser", "shared", "intent"):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

LABEL = "fixture sanity, not a research result"
LINKER_NAMES = ("explicit", "lexical", "identifier", "structural")


def _load_fixture_loader():
    path = ROOT / "benchmarks" / "fixtures" / "intent" / "loader.py"
    spec = importlib.util.spec_from_file_location("intent_fixture_loader", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rank_metrics(rankings: dict[str, list[tuple]], gold: dict[str, set[tuple]]) -> dict:
    """Top-1 / Top-3 / MRR of ranked chain keys against gold chain sets."""

    scored = [(c, g) for c, g in sorted(gold.items()) if g]
    if not scored:
        return {"n": 0, "top1": 0.0, "top3": 0.0, "mrr": 0.0}
    top1 = top3 = 0
    rr = 0.0
    for cid, g in scored:
        first = next(
            (i for i, key in enumerate(rankings.get(cid, ()), 1) if key in g), None
        )
        if first is None:
            continue
        top1 += first <= 1
        top3 += first <= 3
        rr += 1.0 / first
    n = len(scored)
    return {
        "n": n,
        "top1": round(top1 / n, 4),
        "top3": round(top3 / n, 4),
        "mrr": round(rr / n, 4),
    }


def evaluate_fixture(fixture, calibration=None) -> dict:
    from radius_analysis.symbol_changes import DictSnapshot, extract_symbol_changes
    from radius_linking.application import (
        ChainConfig,
        LinkingConfig,
        build_support_links,
        link_criteria,
    )
    from radius_linking.domain import CriterionInput, SymbolTestEdge
    from radius_linking.infrastructure.linkers import ChangePriorLinker, default_linkers
    from radius_linking.infrastructure.neighbors import CallGraphNeighbors
    from radius_linking.infrastructure.symbol_docs import build_symbol_docs
    from radius_testing.linking import (
        LinkTarget,
        NamingLinker,
        StaticLinker,
        combine_links,
    )
    from radius_testing.linking.model import normalize_test_id

    expected = fixture.expected
    base, head = fixture.base, fixture.head
    changeset = extract_symbol_changes(
        DictSnapshot(base), DictSnapshot(head), fixture.patch_text()
    )
    docs = build_symbol_docs(changeset, DictSnapshot(head), DictSnapshot(base))
    criteria = [
        CriterionInput(c["id"], c["text"], c.get("testability_rationale"))
        for c in expected["criteria"]
    ]
    linkset = link_criteria(
        criteria,
        docs,
        linkers=default_linkers(),
        prior=ChangePriorLinker(),
        config=LinkingConfig(),
        neighbors=CallGraphNeighbors(head, [d.ref for d in docs]),
        snapshot_id=fixture.id,
        changeset_ref="fixture",
    )
    targets = [LinkTarget.from_changed_symbol(s) for s in changeset.symbols]
    s2t = combine_links(
        static=StaticLinker().link(head, targets),
        naming=NamingLinker().link(head, targets),
    )
    edges = [SymbolTestEdge.from_object(link) for link in s2t.links]
    outcomes = {
        normalize_test_id(t): v
        for t, v in (expected.get("test_outcomes", {}).get("head") or {}).items()
    }
    status = {
        e.test_id: outcomes.get(normalize_test_id(e.test_id), "unknown") for e in edges
    }
    ref_of = {d.symbol_id: d.ref for d in docs}
    cids = [c.criterion_id for c in criteria]
    res = build_support_links(
        cids,
        linkset.links,
        edges,
        symbols={d.symbol_id: d for d in docs},
        test_status=status,
        config=ChainConfig(),
        criterion_calibration=calibration,
    )

    gold_syms: dict[str, set[str]] = {}
    gold_chains: dict[str, set[tuple]] = {}
    for g in expected.get("links", []):
        gold_syms.setdefault(g["criterion"], set()).add(g["symbol"])
        for t in g.get("tests", []):
            gold_chains.setdefault(g["criterion"], set()).add(
                (g["symbol"], normalize_test_id(t))
            )
    rankings = {
        cs.criterion_id: [
            (ref_of.get(ch.symbol_id, ch.symbol_id), normalize_test_id(ch.test_id))
            for ch in cs.chains
        ]
        for cs in res.criteria
    }
    triples = {(c, s, t) for c, ks in gold_chains.items() for s, t in ks}
    found = {
        (cs.criterion_id, *key)
        for cs in res.criteria
        for key in rankings[cs.criterion_id]
    }
    chain_scores: list[float] = []
    chain_labels: list[int] = []
    crit_scores: list[float] = []
    crit_labels: list[int] = []
    expected_untested_ok = expected_untested = 0
    for cs in res.criteria:
        crit_scores.append(cs.link_confidence)
        crit_labels.append(1 if gold_chains.get(cs.criterion_id) else 0)
        if gold_syms.get(cs.criterion_id) and not gold_chains.get(cs.criterion_id):
            expected_untested += 1
            expected_untested_ok += cs.link_confidence == 0.0
        for ch, key in zip(cs.chains, rankings[cs.criterion_id], strict=True):
            chain_scores.append(ch.chain_score)
            chain_labels.append(1 if key in gold_chains.get(cs.criterion_id, ()) else 0)
    return {
        "fixture": fixture.id,
        "chain_rank": rank_metrics(rankings, gold_chains),
        "gold_triples": len(triples),
        "triples_found": len(triples & found),
        "expected_untested": expected_untested,
        "expected_untested_zero_confidence": int(expected_untested_ok),
        "criteria": [
            {
                "criterion": cs.criterion_id,
                "link_confidence": cs.link_confidence,
                "score_kind": cs.score_kind,
                "unlinked_reason": cs.unlinked_reason,
                "top_chain": (
                    [rankings[cs.criterion_id][0][0], rankings[cs.criterion_id][0][1]]
                    if cs.chains
                    else None
                ),
            }
            for cs in res.criteria
        ],
        "_chain_scores": chain_scores,
        "_chain_labels": chain_labels,
        "_crit_scores": crit_scores,
        "_crit_labels": crit_labels,
        "_rankings": rankings,
        "_gold_chains": {k: sorted(v) for k, v in gold_chains.items()},
    }


def aggregate(results: list[dict], bins: int) -> dict:
    from radius_linking.domain import reliability_report

    rankings: dict[str, list[tuple]] = {}
    gold: dict[str, set[tuple]] = {}
    for r in results:  # namespace criterion ids by fixture
        for cid, ranked in r["_rankings"].items():
            rankings[f"{r['fixture']}/{cid}"] = ranked
        for cid, ks in r["_gold_chains"].items():
            gold[f"{r['fixture']}/{cid}"] = {tuple(k) for k in ks}
    out = {
        "chain_rank": rank_metrics(rankings, gold),
        "gold_triples": sum(r["gold_triples"] for r in results),
        "triples_found": sum(r["triples_found"] for r in results),
        "expected_untested": sum(r["expected_untested"] for r in results),
        "expected_untested_zero_confidence": sum(
            r["expected_untested_zero_confidence"] for r in results
        ),
    }
    out["triple_recall"] = (
        round(out["triples_found"] / out["gold_triples"], 4)
        if out["gold_triples"]
        else None
    )
    for name, sk, lk in (
        ("chain_reliability", "_chain_scores", "_chain_labels"),
        ("criterion_reliability", "_crit_scores", "_crit_labels"),
    ):
        scores = [s for r in results for s in r[sk]]
        labels = [y for r in results for y in r[lk]]
        if scores and 0 < sum(labels) < len(labels):
            out[name] = reliability_report(scores, labels, bins)
        else:
            out[name] = {
                "note": "needs both positive and negative labels",
                "n": len(scores),
            }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixtures", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument(
        "--calibrator",
        type=Path,
        default=None,
        help="fitted criterion-target calibration artifact (JSON)",
    )
    args = parser.parse_args(argv)

    from radius_linking.domain import CalibrationArtifact

    artifact = (
        CalibrationArtifact.from_json(args.calibrator.read_text(encoding="utf-8"))
        if args.calibrator
        else None
    )
    loader = _load_fixture_loader()
    if args.fixtures is not None:
        loader.FIXTURES_DIR = args.fixtures
    results = [evaluate_fixture(fx, artifact) for fx in loader.discover()]
    agg = aggregate(results, args.bins)
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    report = {
        "schema_version": 1,
        "label": LABEL,
        "algo": "link-chain-v1",
        "score_kind": (
            "link_confidence_calibrated" if artifact else "link_confidence_uncalibrated"
        ),
        "dynamic_linker": "not run (needs sandbox)",
        "fixtures": public,
        "aggregate": agg,
    }
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(text)
        return 0
    print(f"LK-06 chain evaluation on {len(results)} fixtures ({LABEL})")
    print(f"score kind: {report['score_kind']}; dynamic linker: not run\n")
    m = agg["chain_rank"]
    print(
        f"chain rank   n={m['n']} top1={m['top1']:.3f} top3={m['top3']:.3f} mrr={m['mrr']:.3f}"
    )
    print(
        f"gold triples {agg['triples_found']}/{agg['gold_triples']} found; "
        f"untested criteria with zero confidence "
        f"{agg['expected_untested_zero_confidence']}/{agg['expected_untested']}"
    )
    for name in ("chain_reliability", "criterion_reliability"):
        rep = agg[name]
        if "ece" in rep:
            print(
                f"{name}: n={rep['n']} ece={rep['ece']:.3f} mce={rep['mce']:.3f} "
                f"brier={rep['brier']:.3f}"
            )
        else:
            print(f"{name}: {rep['note']} (n={rep['n']})")
    print("\nper fixture:")
    for r in public:
        confs = ", ".join(
            f"{c['criterion']}={c['link_confidence']:.2f}"
            + (f"[{c['unlinked_reason']}]" if c["unlinked_reason"] else "")
            for c in r["criteria"]
        )
        print(f"  {r['fixture']:<38} {confs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
