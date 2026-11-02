#!/usr/bin/env python3
"""Criterion -> test relevance (``r_ct``, VS-04) evaluation on the F-14 fixtures.

    python scripts/relevance_eval.py [--fixtures DIR] [--threshold 0.3] [--json] [--out FILE]

For each fixture (``benchmarks/fixtures/intent/*``):

* test documents are built from the head test files with a light ``ast`` extractor
  (name, docstring, parametrize ids, ``assert`` and ``pytest.raises`` facts). This is
  NOT the LK-04 extractor; the relevance module consumes plain ``TestDoc`` data and
  this script is only an adapter for the fixtures;
* a (criterion, test) pair is "connected" when the test calls the gold symbol of the
  criterion. That is exactly the situation of finding F4: a function implementing
  several criteria connects every one of its tests to every one of its criteria;
* precision / recall of ``r_ct >= threshold`` is computed against the gold
  ``links[].tests`` of ``expected.json``, next to the baseline "every connected test
  gets credit" (what the symbol-test link alone would give).

THE NUMBERS ARE A FIXTURE SANITY CHECK, NOT A RESEARCH RESULT: eight tiny hand-written
PRs, constants set while looking at them (in-sample). No claim about generalisation.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _pkg in ("linking",):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

LABEL = "fixture sanity, not a research result"


def _load_loader():
    path = ROOT / "benchmarks" / "fixtures" / "intent" / "loader.py"
    spec = importlib.util.spec_from_file_location("intent_fixture_loader", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_names(node: ast.AST) -> tuple[str, ...]:
    names = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            names.append(
                f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            )
    return tuple(sorted({x for x in names if x}))


def _dotted(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return ""


def test_docs_from_source(path: str, source: str):
    """``TestDoc``s of the top-level ``test_*`` functions of one Python file."""

    from radius_linking.domain import AssertionFact, TestDoc

    docs = []
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test")):
            continue
        facts, lits, params = [], [], []
        for dec in node.decorator_list:
            if "parametrize" in _dotted(dec):
                params += [
                    c.value
                    for c in ast.walk(dec)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                ]
        for n in ast.walk(node):
            if isinstance(n, ast.Assert):
                test = n.test
                subject, expected = test, None
                if isinstance(test, ast.Compare) and test.comparators:
                    subject, expected = test.left, test.comparators[0]
                kind = "equality" if isinstance(test, ast.Compare) else "truthiness"
                if isinstance(test, ast.Call) and _dotted(test.func) == "isinstance":
                    kind = "type_check"
                facts.append(
                    AssertionFact(
                        _dotted(subject),
                        _dotted(expected) if expected is not None else "",
                        kind,
                        _call_names(subject),
                    )
                )
            elif isinstance(n, ast.With):
                for item in n.items:
                    call = item.context_expr
                    if isinstance(call, ast.Call) and _dotted(call.func).endswith(
                        "raises"
                    ):
                        exc = _dotted(call.args[0]) if call.args else ""
                        body = " ".join(_dotted(s) for s in n.body)
                        facts.append(
                            AssertionFact(body, exc, "exception", _call_names(n), exc)
                        )
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                lits.append(n.value)
        docs.append(
            TestDoc(
                f"{path}::{node.name}",
                node.name,
                ast.get_docstring(node) or "",
                tuple(params),
                tuple(facts),
                tuple(lits),
            )
        )
    return docs


def evaluate_fixture(fixture, threshold: float) -> dict:
    from radius_linking.application import RelevanceConfig, score_relevance
    from radius_linking.domain import CriterionInput

    head = fixture.head
    docs = []
    for rel, text in sorted(head.items()):
        if (
            rel.endswith(".py")
            and "/tests/" in "/" + rel
            and Path(rel).name.startswith("test")
        ):
            docs.extend(test_docs_from_source(rel, text))
    per_fn: dict[str, set[str]] = {}
    for rel in {d.test_id.split("::")[0] for d in docs}:
        for node in ast.parse(head[rel]).body:
            if isinstance(node, ast.FunctionDef):
                per_fn[f"{rel}::{node.name}"] = set(_call_names(node))
    expected = fixture.expected
    criteria = [CriterionInput(c["id"], c["text"]) for c in expected["criteria"]]
    connections: dict[tuple[str, str], tuple[str, ...]] = {}
    gold: set[tuple[str, str]] = set()
    for link in expected["links"]:
        sym = link["symbol"]
        fn = sym.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        for tid, called in per_fn.items():
            if tid in {d.test_id for d in docs} and fn in called:
                connections[(link["criterion"], tid)] = (sym,)
        gold |= {(link["criterion"], t) for t in link["tests"]}
    result = score_relevance(criteria, docs, connections, RelevanceConfig())
    pred = {(i.criterion_id, i.test_id) for i in result.items if i.r_ct >= threshold}
    base = set(connections)
    return {
        "fixture": fixture.id,
        "gold": sorted(gold),
        "connected": len(base),
        "predicted": sorted(pred),
        "tp": len(pred & gold),
        "fp": len(pred - gold),
        "fn": len(gold - pred),
        "baseline_tp": len(base & gold),
        "baseline_fp": len(base - gold),
        "scores": {
            f"{i.criterion_id}|{i.test_id.split('::')[-1]}": i.r_ct
            for i in result.items
        },
        "reasons": {
            f"{i.criterion_id}|{i.test_id.split('::')[-1]}": [r.code for r in i.reasons]
            for i in result.items
        },
        "criteria_without_gold_tests": sorted(
            c["id"]
            for c in expected["criteria"]
            if not any(g[0] == c["id"] for g in gold)
        ),
    }


def _pr(tp: int, fp: int, fn: int) -> tuple[float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return round(p, 4), round(r, 4)


def aggregate(results: list[dict]) -> dict:
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    btp = sum(r["baseline_tp"] for r in results)
    bfp = sum(r["baseline_fp"] for r in results)
    p, rc = _pr(tp, fp, fn)
    bp, brc = _pr(btp, bfp, fn + tp - btp)
    return {
        "label": LABEL,
        "fixtures": len(results),
        "r_ct": {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": rc},
        "baseline_all_connected": {
            "tp": btp,
            "fp": bfp,
            "precision": bp,
            "recall": brc,
        },  # fmt: skip
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--fixtures", type=Path, default=ROOT / "benchmarks" / "fixtures" / "intent"
    )
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    loader = _load_loader()
    loader.FIXTURES_DIR = args.fixtures
    fixtures = loader.discover()
    results = [evaluate_fixture(f, args.threshold) for f in fixtures]
    summary = aggregate(results)
    report = {"summary": summary, "threshold": args.threshold, "fixtures": results}
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(text)
        return 0
    print(f"r_ct fixture evaluation ({LABEL}), threshold {args.threshold}")
    for r in results:
        p, rc = _pr(r["tp"], r["fp"], r["fn"])
        print(
            f"  {r['fixture']:45s} gold={len(r['gold']):2d} connected={r['connected']:2d} "
            f"tp={r['tp']} fp={r['fp']} fn={r['fn']} P={p} R={rc}"
        )
        for k, v in sorted(r["scores"].items()):
            print(f"      {k:50s} {v:.3f}  {','.join(r['reasons'][k])}")
    print(
        "summary:",
        json.dumps(summary["r_ct"]),
        "baseline:",
        json.dumps(summary["baseline_all_connected"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
