#!/usr/bin/env python
"""Fixture sanity run of the WIRED mutation evidence (NOT a research result).

Runs the real Verdict v2 Stage A + B on the 8 F-14 fixtures twice per mode: flag OFF
(static) and flag ON, where the Stage A ``mutation`` producer measures the changed
symbols with the DEV-ONLY local runner. The local runner executes code on this host and
is allowed here only because the F-14 fixtures are our own trusted code; it still needs
an explicit opt-in::

    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_wired_eval.py
    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_wired_eval.py 01 08 --mode gold --json out.json
    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_wired_eval.py --stage2   # adds ON stage1+2

The worker never does this: in the worker the producer is sandbox-only
(``radius_worker.verdict_v2.mutation``). Output: per fixture and mode, verdict and the
support S(c) of every criterion OFF versus ON, plus the measured basis and survivors.
Disagreements with the static result (and with the fixture's labelled expectation) are
listed, not hidden.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def _load_runner_module() -> Any:
    spec = importlib.util.spec_from_file_location("verdict_v2_run_mod", HERE / "verdict_v2_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_runner_module()


def local_dev_producer(max_mutants: int, wall_clock: float, stage2: bool = False):
    """Dev-only ``Producers.mutation``: the same selection and measurement as the worker."""

    from radius_testing.mutation import (
        MeasureConfig,
        MutationBudget,
        SubprocessLocalRunner,
        measure_mutation,
    )
    from radius_worker.verdict_v2.mutation import (
        select_targets,
        to_input,
        unmeasured_input,
    )

    def produce(req: Any) -> Any:
        targets = select_targets(req)
        if not targets:
            return unmeasured_input("no_linked_changed_symbols")
        cfg = MeasureConfig(
            budget=MutationBudget(
                max_mutants=max_mutants, wall_clock_seconds=wall_clock,
                per_mutant_timeout_seconds=60.0,
            ),
            stage2=stage2,
        )
        with SubprocessLocalRunner(req.repository_path) as runner:
            m = measure_mutation(
                runner, req.repository_path, targets, cfg, allow_local_runner=True
            )
        return to_input(m)

    return produce


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": payload["verdict"],
        "decided_by": payload["justification"]["decided_by"],
        "evidence_basis": payload["evidence_basis"],
        "criteria": {
            c["criterion_id"]: {
                "state": c["state"],
                "S": c["S"],
                "basis": c.get("evidence_basis", "static_only"),
                "n_mutants": (c.get("mutation") or {}).get("n_mutants"),
                "killed": (c.get("mutation") or {}).get("killed"),
                "survivors": [
                    f"{s['path']}:{s['line']} {s['operator']}"
                    for s in (c.get("mutation") or {}).get("survivors", [])
                ],
                "link_gaps": len((c.get("mutation") or {}).get("link_gaps", [])),
                "link_gap_tests": (c.get("mutation") or {}).get("link_gap_tests", []),
                "tests": {
                    i["test_id"].rsplit("::", 1)[-1]: {
                        "a_static": i["a_static"], "d_eff": i["d_eff"],
                        "mutation_n": i.get("mutation_n"), "killed": i.get("mutation_killed"),
                    }
                    for i in c["items"]
                    if i["status"] == "counted" or i.get("basis") == "mutation"
                },
            }
            for c in payload["criteria"]
        },
        "mutation_run": payload.get("mutation"),
        "degraded": payload.get("degraded", []),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixtures", nargs="*")
    ap.add_argument("--mode", choices=("gold", "auto", "both"), default="gold")
    ap.add_argument("--max-mutants", type=int, default=50)
    ap.add_argument("--wall-clock", type=float, default=600.0)
    ap.add_argument("--stage2", action="store_true", help="also run ON with stage 2 (wider tests)")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    if os.environ.get("RADIUS_MUTATION_ALLOW_LOCAL") != "1":
        raise SystemExit(
            "refusing to run: this executes the fixture tests locally. Set "
            "RADIUS_MUTATION_ALLOW_LOCAL=1 (trusted F-14 fixtures only)."
        )
    expectations = {
        f["fixture"]: f for f in json.loads(RUN.EXPECT.read_text(encoding="utf-8"))["fixtures"]
    }
    modes = ("gold", "auto") if args.mode == "both" else (args.mode,)
    producer = local_dev_producer(args.max_mutants, args.wall_clock)
    producer2 = local_dev_producer(args.max_mutants, args.wall_clock, stage2=True)
    out: dict[str, Any] = {}
    for path in RUN.fixture_dirs(args.fixtures):
        for mode in modes:
            off = RUN.run_collect(path, mode, "static")
            on = RUN.run_collect(path, mode, "static", mutation=producer)
            a, b = summarize(off), summarize(on)
            out[f"{path.name}:{mode}"] = {"off": a, "on": b}
            if args.stage2:
                on2 = RUN.run_collect(path, mode, "static", mutation=producer2)
                c2 = summarize(on2)
                out[f"{path.name}:{mode}"]["on_stage2"] = c2
                st2 = (c2["mutation_run"] or {}).get("stage2")
                print(f"   stage2    verdict {c2['verdict']:<22} stage2={st2}")
                for cid, cb in b["criteria"].items():
                    cc = c2["criteria"][cid]
                    print(f"   {cid:<3} ON1 {cb['state']:<12} {cb['S']:.3f} n={cb['n_mutants']}  "
                          f"ON1+2 {cc['state']:<12} {cc['S']:.3f} n={cc['n_mutants']} "
                          f"link_gaps={cc['link_gaps']} {cc['link_gap_tests']}")
            exp = expectations[path.name]
            print(f"\n== {path.name} [{mode}]  expected verdict: {exp['expected_verdict']}")
            print(f"   verdict   OFF {a['verdict']:<22} ON {b['verdict']:<22} "
                  f"basis ON: {b['evidence_basis']}")
            run = b["mutation_run"] or {}
            print(f"   mutation  status={run.get('status')} reason={run.get('reason') or '-'} "
                  f"generated={run.get('generated')} decided={run.get('decided')} "
                  f"killed={run.get('killed')} ladder={run.get('ladder')}")
            for cid, ca in a["criteria"].items():
                cb = b["criteria"][cid]
                flag = "" if (ca["state"], ca["S"]) == (cb["state"], cb["S"]) else "  <- changed"
                print(f"   {cid:<3} OFF {ca['state']:<12} {ca['S']:.3f}   ON {cb['state']:<12} "
                      f"{cb['S']:.3f}  basis={cb['basis']} n={cb['n_mutants']} "
                      f"killed={cb['killed']}{flag}")
                for t, v in cb["tests"].items():
                    if v["mutation_n"] is not None:
                        print(f"        {t}: a_static={v['a_static']:.2f} -> d_eff={v['d_eff']:.3f} "
                              f"({v['killed']}/{v['mutation_n']} killed)")
                if cb["survivors"]:
                    print(f"        gaps: {', '.join(cb['survivors'][:6])}"
                          f"{' ...' if len(cb['survivors']) > 6 else ''}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
