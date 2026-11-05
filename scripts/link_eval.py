"""Criterion -> symbol link evaluation hook (LK-02).

    python scripts/link_eval.py [--fixtures DIR] [--k 3] [--json] [--out FILE]

For each golden fixture (F-14, ``benchmarks/fixtures/intent/*``) this extracts
the changed symbols from ``pr.patch`` (LK-01), links the fixture criteria with
the deterministic linkers (LK-02) and scores the ranking against the
``links`` of ``expected.json``: Top-1, Top-3, MRR for the combined ranking, for
each linker alone, and a leave-one-out / only-one ablation of the combiner.

IMPORTANT: this is a measurement hook. The F-14 fixtures are tiny (one to a few
changed symbols per PR, written by the project), so the numbers are a *fixture
sanity check, not a research result*. The RQ1 evaluation runs on the LK-07 gold
set. Needs PYTHONPATH like CI (packages/*/src) and no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "fixture sanity, not a research result"
LINKER_NAMES = ("explicit", "lexical", "identifier", "structural")


def _load_fixture_loader():
    path = ROOT / "benchmarks" / "fixtures" / "intent" / "loader.py"
    spec = importlib.util.spec_from_file_location("intent_fixture_loader", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def evaluate_fixture(fixture, *, k: int = 3) -> dict:
    from radius_analysis.symbol_changes import DictSnapshot, extract_symbol_changes
    from radius_linking.application import (
        LinkingConfig,
        ablation,
        evaluate_linkset,
        gold_from_expected,
        link_criteria,
        links_as_expected,
    )
    from radius_linking.domain import CriterionInput
    from radius_linking.infrastructure.linkers import ChangePriorLinker, default_linkers
    from radius_linking.infrastructure.neighbors import CallGraphNeighbors
    from radius_linking.infrastructure.symbol_docs import build_symbol_docs

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
    neighbors = CallGraphNeighbors(head, [d.ref for d in docs])
    linkers = default_linkers()
    prior = ChangePriorLinker()

    def run(enabled: frozenset[str]):
        return link_criteria(
            criteria,
            docs,
            linkers=[x for x in linkers if x.name in enabled],
            prior=prior,
            config=LinkingConfig(),
            neighbors=neighbors,
            snapshot_id=fixture.id,
            changeset_ref="fixture",
        )

    linkset = run(frozenset(LINKER_NAMES))
    gold = gold_from_expected(expected)
    per = evaluate_linkset(
        linkset, docs, gold, linker_names=(*LINKER_NAMES, "change_prior")
    )
    abl = ablation(run, LINKER_NAMES, docs, gold)
    return {
        "fixture": fixture.id,
        "candidate_symbols": [d.ref for d in docs if not d.is_test],
        "metrics": {name: m.to_dict() for name, m in per.items()},
        "ablation": {name: m.to_dict() for name, m in abl.items()},
        "predicted_links": links_as_expected(linkset, docs, k=k),
        "gold_links": [
            {"criterion": c, "symbol": s}
            for c, ss in sorted(gold.items())
            for s in sorted(ss)
        ],
    }


def aggregate(results: list[dict]) -> dict:
    """Criterion-weighted mean of the per-fixture metrics (micro average)."""

    def merge(key: str, name: str) -> dict:
        rs = [r for r in results if name in r[key]]
        total = sum(r[key][name]["n"] for r in rs)
        if not total:
            return {"n": 0, "top1": 0.0, "top3": 0.0, "mrr": 0.0}
        return {
            "n": total,
            **{
                m: round(
                    sum(r[key][name][m] * r[key][name]["n"] for r in rs) / total, 4
                )
                for m in ("top1", "top3", "mrr")
            },
        }

    names = sorted({n for r in results for n in r["metrics"]})
    abl_names = sorted({n for r in results for n in r["ablation"]})
    return {
        "metrics": {n: merge("metrics", n) for n in names},
        "ablation": {n: merge("ablation", n) for n in abl_names},
    }


def format_table(title: str, rows: dict[str, dict]) -> str:
    lines = [title, f"{'name':<24}{'n':>4}{'top1':>8}{'top3':>8}{'mrr':>8}"]
    for name, m in rows.items():
        lines.append(
            f"{name:<24}{m['n']:>4}{m['top1']:>8.3f}{m['top3']:>8.3f}{m['mrr']:>8.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--fixtures", type=Path, default=None, help="fixture root (default F-14)"
    )
    parser.add_argument(
        "--k", type=int, default=3, help="predicted links per criterion in output"
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of tables"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="also write the JSON here"
    )
    args = parser.parse_args(argv)

    loader = _load_fixture_loader()
    if args.fixtures is not None:
        loader.FIXTURES_DIR = args.fixtures  # honoured by discover() when present
    fixtures = loader.discover()
    results = [evaluate_fixture(fx, k=args.k) for fx in fixtures]
    report = {
        "schema_version": 1,
        "label": LABEL,
        "algo": "criterion-symbol-links-v1",
        "fixtures": results,
        "aggregate": aggregate(results),
    }
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(text)
    else:
        print(f"LK-02 link evaluation on {len(results)} fixtures ({LABEL})\n")
        print(format_table("combined and per-linker", report["aggregate"]["metrics"]))
        print()
        print(
            format_table(
                "ablation of the combined ranking", report["aggregate"]["ablation"]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
