#!/usr/bin/env python
"""Mutation fixture sanity run on the F-14 intent fixtures (NOT a research result).

For each fixture HEAD tree: mutate the LK-01 changed symbols, run the fixture tests
against every mutant with the dev-only local runner, build the kill matrix and
compare the measured test strength with the fixture's labelled band
(``expected.json``) and with ``a_static`` (LK-04 + EV-06).

SAFETY: the local runner executes code on this host. It is allowed here only because
the F-14 fixtures are our own trusted code, and it still refuses to start unless you
opt in explicitly::

    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_fixture_eval.py
    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_fixture_eval.py 03 08 --json out.json

Band rules (fixed before the run, not tuned afterwards; see MUTATION_FIXTURES.md):

* ``d_reach`` (headline) = killed_by(t) / mutants of the changed symbols whose line t
  executes. none: kills nothing; strong: d_reach >= 0.5; weak: otherwise;
  ``n/a`` when t reaches fewer than 3 non-equivalent mutants.
* ``d_mut`` (EV-05 literal) = killed_by(t) / all non-equivalent mutants of the
  linked symbols. none: 0 kills; strong: >= 0.20; weak otherwise; ``n/a`` below 5.
* ``a_static`` band: strong >= 0.6, weak in (0, 0.6), none == 0.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _src in sorted((ROOT / "packages").glob("*/src")):
    if str(_src) not in sys.path:
        sys.path.append(str(_src))

from radius_analysis.symbol_changes import (  # noqa: E402
    DirectorySnapshot,
    extract_symbol_changes,
)
from radius_evidence.domain.assertion_records import features_from_assertion_set  # noqa: E402
from radius_evidence.domain.strength import a_static  # noqa: E402
from radius_testing.assertions import extract_assertions  # noqa: E402
from radius_testing.mutation import (  # noqa: E402
    OPERATOR_IDS,
    MutationBudget,
    SubprocessLocalRunner,
    aggregate_criterion,
    d_mut_per_test,
    generate_mutants,
    run_mutants,
    sample_mutants,
)

FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
REACH_PLUGIN = '''
import json, os, sys
import pytest

_FILES = {os.path.normcase(os.path.realpath(p)) for p in os.environ["RADIUS_REACH_FILES"].split(os.pathsep)}
_OUT = os.environ["RADIUS_REACH_OUT"]
_DATA = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    seen = set()

    def tracer(frame, event, arg):
        name = os.path.normcase(os.path.realpath(frame.f_code.co_filename))
        if name not in _FILES:
            return None

        def local(frame, event, arg):
            if event == "line":
                seen.add(frame.f_lineno)
            return local

        seen.add(frame.f_lineno)
        return local

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(old)
        _DATA[item.nodeid.replace("\\\\", "/")] = sorted(seen)


def pytest_sessionfinish(session):
    with open(_OUT, "w") as fh:
        json.dump(_DATA, fh)
'''

MIN_REACH = 3
MIN_ALL = 5
STRONG_REACH = 0.5
STRONG_ALL = 0.20
STRONG_ASTATIC = 0.6


def band_from_d(killed: float, d: float | None, strong_at: float) -> str:
    if d is None:
        return "n/a"
    if killed == 0:
        return "none"
    return "strong" if d >= strong_at else "weak"


def band_from_a(a: float) -> str:
    if a <= 0:
        return "none"
    return "strong" if a >= STRONG_ASTATIC else "weak"


def changed_scopes(base: Path, head: Path, patch: str):
    """LK-01 changed behavioural symbols in non-test python files: {path: [(label, range)]}."""
    cs = extract_symbol_changes(DirectorySnapshot(base), DirectorySnapshot(head), patch)
    out: dict[str, list[tuple[str, tuple[int, int]]]] = {}
    for s in cs.symbols:
        if not s.path.endswith(".py") or s.path.startswith("tests/") or s.new_range is None:
            continue
        if not s.is_behavioral:
            continue
        out.setdefault(s.path, []).append(
            (f"{s.path}::{s.qualified_name}", (s.new_range.start, s.new_range.end))
        )
    return out


def innermost(label_ranges, line: int) -> str:
    best, span = None, 10**9
    for label, (a, b) in label_ranges:
        if a <= line <= b and b - a < span:
            best, span = label, b - a
    return best or "<unscoped>"


def measure_reach(head: Path, files: list[str], mutants) -> dict[str, set[str]]:
    """Per-test executed-line reach of the mutated files (trusted fixture code only)."""
    tmp = Path(tempfile.mkdtemp(prefix="radius-reach-"))
    try:
        ws = tmp / "ws"
        shutil.copytree(head, ws, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        (tmp / "radius_reach_plugin.py").write_text(REACH_PLUGIN, encoding="utf-8")
        out = tmp / "reach.json"
        env = {
            k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ
        }
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            PYTHONPATH=str(tmp),
            RADIUS_REACH_FILES=os.pathsep.join(str(ws / f) for f in files),
            RADIUS_REACH_OUT=str(out),
        )
        subprocess.run(  # noqa: S603 - trusted fixture, dev-only script
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
             "-p", "radius_reach_plugin", "tests"],
            cwd=ws, env=env, capture_output=True, timeout=120, check=False,
        )
        lines = json.loads(out.read_text()) if out.is_file() else {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    reach: dict[str, set[str]] = {}
    for test, executed in lines.items():
        got = set(executed)
        reach[test] = {m.id for m in mutants if m.lineno in got}
    return reach


def evaluate(
    fx: Path, max_mutants: int, seed: int, timeout: float, baseline_runs: int, survivor_reruns: int,
    operators: tuple[str, ...] = OPERATOR_IDS,
) -> dict:
    expected = json.loads((fx / "expected.json").read_text(encoding="utf-8"))
    base, head = fx / "base", fx / "head"
    patch = (fx / "pr.patch").read_text(encoding="utf-8")
    started = time.monotonic()
    scopes = changed_scopes(base, head, patch)
    all_mutants = []
    sources = {}
    for path, items in sorted(scopes.items()):
        text = (head / path).read_text(encoding="utf-8")
        sources[path] = text
        ranges = [r for _, r in items]
        all_mutants += generate_mutants(text, path, ranges, operators)
    mutants = sample_mutants(all_mutants, max_mutants, seed)
    labels = {p: items for p, items in scopes.items()}
    relabel = {m.id: innermost(labels[m.path], m.lineno) for m in mutants}

    with SubprocessLocalRunner(head) as runner:
        run = run_mutants(
            runner, mutants, ["tests"],
            MutationBudget(max_mutants=max_mutants, per_mutant_timeout_seconds=timeout, seed=seed),
            original_sources=sources, baseline_runs=baseline_runs, survivor_reruns=survivor_reruns,
        )
    records = tuple(dataclasses.replace(r, symbol=relabel[r.id]) for r in run.matrix.records)
    matrix = dataclasses.replace(run.matrix, records=records)
    reach = measure_reach(head, sorted(scopes), mutants)
    # module-level (import-time) mutants are reached by every test
    for m in mutants:
        if m.symbol == "<module>":
            for t in matrix.tests:
                reach.setdefault(t, set()).add(m.id)

    test_files = sorted({t.split("::")[0] for t in matrix.tests})
    snap = {p: (head / p).read_text(encoding="utf-8") for p in test_files}
    aset = extract_assertions(test_files, snap)
    feats = {f.test_id: f for f in features_from_assertion_set(aset.to_dict()).features}
    a_by_test = {t: (a_static(feats[t]) if t in feats else 0.0) for t in matrix.tests}

    linked_symbols = {lk["symbol"] for lk in expected["links"]}
    all_syms = sorted({r.symbol for r in matrix.records})
    d_all = {d.test: d for d in d_mut_per_test(matrix, all_syms, min_mutants=MIN_ALL)}
    d_rch = {d.test: d for d in d_mut_per_test(matrix, all_syms, min_mutants=MIN_REACH, reach=reach)}
    bands = {b["test"]: b["band"] for b in expected["evidence_quality"]}

    tests = []
    for t in sorted(set(matrix.tests) | set(bands)):
        a = a_by_test.get(t)
        da, dr = d_all.get(t), d_rch.get(t)
        if t not in matrix.tests:
            tests.append({"test": t, "expected": bands.get(t), "note": "not passing at HEAD"})
            continue
        tests.append(
            {
                "test": t,
                "expected": bands.get(t),
                "a_static": round(a, 3),
                "a_band": band_from_a(a),
                "killed": da.killed,
                "n_all": da.n,
                "d_mut": None if da.d_mut is None else round(da.d_mut, 3),
                "n_reach": dr.n,
                "killed_reach": dr.killed,
                "d_reach": None if dr.d_mut is None else round(dr.d_mut, 3),
                "d_reach_lcb": None if dr.lcb is None else round(dr.lcb, 3),
                "band_reach": band_from_d(dr.killed, dr.d_mut, STRONG_REACH),
                "band_mut": band_from_d(da.killed, da.d_mut, STRONG_ALL),
            }
        )
    criteria = []
    for lk in expected["links"]:
        agg = aggregate_criterion(matrix, [lk["symbol"]], lk["tests"], min_mutants=MIN_ALL)
        surv = [r for r in matrix.records if r.id in set(agg.survivors)]
        by_id = {m.id: m for m in mutants}
        criteria.append(
            {
                "criterion": lk["criterion"],
                "symbol": lk["symbol"],
                "tests": lk["tests"],
                "n": agg.n_mutants,
                "killed_by_linked": agg.killed_by_any,
                "union_d": None if agg.union_d is None else round(agg.union_d, 3),
                "lcb": None if agg.union_lcb is None else round(agg.union_lcb, 3),
                "survivors": [
                    f"{by_id[r.id].operator}@{by_id[r.id].lineno}: {by_id[r.id].replacement}"
                    for r in surv
                ],
                "reason": agg.reason,
            }
        )
    status = {}
    for r in matrix.records:
        key = "equivalent_suspect" if r.equivalent_suspect else r.status
        status[key] = status.get(key, 0) + 1
    unlinked = [s for s in all_syms if s not in linked_symbols]
    unlinked_stats = {}
    for s in unlinked:
        rs = [r for r in matrix.records if r.symbol == s and not r.equivalent_suspect]
        unlinked_stats[s] = {
            "mutants": len(rs),
            "killed": sum(r.status == "killed" for r in rs),
            "survived": sum(r.status == "survived" for r in rs),
        }
    return {
        "fixture": expected["id"],
        "changed_symbols": sorted({lbl for items in scopes.values() for lbl, _ in items}),
        "generated": len(all_mutants),
        "executed": len(run.outcomes),
        "skipped_for_budget": len(run.skipped_for_budget),
        "status": status,
        "baseline_failed": list(run.baseline_failed),
        "baseline_flaky": list(run.baseline_flaky),
        "tests": tests,
        "criteria": criteria,
        "unlinked_symbols": unlinked_stats,
        "seconds": round(time.monotonic() - started, 1),
    }


def agreement(results: list[dict]) -> dict:
    pairs = {"expected_vs_reach": [], "expected_vs_mut": [], "expected_vs_a": [], "a_vs_reach": []}
    for res in results:
        for t in res["tests"]:
            if "a_band" not in t:
                continue
            exp = t["expected"]
            for key, other in (
                ("expected_vs_reach", t["band_reach"]), ("expected_vs_mut", t["band_mut"]),
                ("expected_vs_a", t["a_band"]),
            ):
                if exp is not None and other != "n/a":
                    pairs[key].append((res["fixture"], t["test"], exp, other))
            if t["band_reach"] != "n/a":
                pairs["a_vs_reach"].append((res["fixture"], t["test"], t["a_band"], t["band_reach"]))
    out = {}
    for key, items in pairs.items():
        agree = sum(1 for *_, x, y in items if x == y)
        out[key] = {"n": len(items), "agree": agree, "disagreements": [i for i in items if i[2] != i[3]]}
    return out


def markdown(results: list[dict], agg: dict) -> str:
    lines: list[str] = []
    for r in results:
        s = ", ".join(f"{k} {v}" for k, v in sorted(r["status"].items()))
        lines += [
            f"### {r['fixture']}",
            "",
            f"Changed symbols: {', '.join(r['changed_symbols']) or 'none'}. Mutants generated "
            f"{r['generated']}, executed {r['executed']} ({s}); baseline failing: "
            f"{r['baseline_failed'] or 'none'}; {r['seconds']} s.",
            "",
            "| test | expected | a_static | kills | n_all | d_mut | n_reach | d_reach | band (reach) | band (d_mut) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for t in r["tests"]:
            name = t["test"].split("::")[-1]
            if "a_band" not in t:
                lines.append(f"| {name} | {t['expected']} | - | - | - | - | - | - | not passing | - |")
                continue
            lines.append(
                f"| {name} | {t['expected']} | {t['a_static']} ({t['a_band']}) | {t['killed']:g} "
                f"| {t['n_all']} | {t['d_mut']} | {t['n_reach']} | {t['d_reach']} | "
                f"{t['band_reach']} | {t['band_mut']} |"
            )
        lines += ["", "| criterion | linked tests | N | killed by any linked | D(c) | lcb | survivors |",
                  "|---|---|---|---|---|---|---|"]
        for c in r["criteria"]:
            surv = "; ".join(c["survivors"][:4]) + (" ..." if len(c["survivors"]) > 4 else "")
            lines.append(
                f"| {c['criterion']} | {len(c['tests'])} | {c['n']} | {c['killed_by_linked']} | "
                f"{c['union_d']} | {c['lcb']} | {surv or '-'} |"
            )
        if r["unlinked_symbols"]:
            lines += ["", "Changed symbols linked to no criterion: "
                      + "; ".join(f"{k} ({v['killed']} killed, {v['survived']} survived of {v['mutants']})"
                                  for k, v in r["unlinked_symbols"].items())]
        lines.append("")
    lines += ["### Agreement", "", "| comparison | n | agree |", "|---|---|---|"]
    for key, v in agg.items():
        lines.append(f"| {key} | {v['n']} | {v['agree']} |")
    lines += ["", "Disagreements (fixture, test, first, second):", ""]
    for key, v in agg.items():
        lines.append(f"- {key}:")
        for fx, test, x, y in v["disagreements"]:
            lines.append(f"  - {fx} {test.split('::')[-1]}: {x} vs {y}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("fixtures", nargs="*", help="fixture id prefixes (default: all)")
    ap.add_argument("--max-mutants", type=int, default=30)
    ap.add_argument("--baseline-runs", type=int, default=1, help="1 keeps runtime small; the unit tests cover flaky handling")
    ap.add_argument("--survivor-reruns", type=int, default=0)
    ap.add_argument("--operators", default=",".join(OPERATOR_IDS), help="comma list; add CALLX for the experimental operator")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--json", type=Path, help="write raw results as JSON")
    ap.add_argument("--markdown", type=Path, help="write the markdown tables")
    args = ap.parse_args(argv)
    if os.environ.get("RADIUS_MUTATION_ALLOW_LOCAL") != "1":
        print("refusing: set RADIUS_MUTATION_ALLOW_LOCAL=1 (executes trusted fixture code locally)",
              file=sys.stderr)
        return 2
    dirs = sorted(p for p in FIXTURES.iterdir() if (p / "expected.json").is_file())
    if args.fixtures:
        dirs = [d for d in dirs if any(d.name.startswith(f) for f in args.fixtures)]
    results = [evaluate(d, args.max_mutants, args.seed, args.timeout, args.baseline_runs, args.survivor_reruns,
                         tuple(args.operators.split(","))) for d in dirs]
    agg = agreement(results)
    text = markdown(results, agg)
    print(text)
    if args.json:
        args.json.write_text(json.dumps({"results": results, "agreement": agg}, indent=2, default=list))
    if args.markdown:
        args.markdown.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
