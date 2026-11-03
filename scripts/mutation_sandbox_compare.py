#!/usr/bin/env python
"""Compare the mutation kill matrix of the dev-only local runner with the F-07 sandbox.

Runs ONE F-14 fixture end to end twice with identical targets, budget and seed: once
through ``SubprocessLocalRunner`` (host process, trusted fixture code only) and once
through ``SandboxMutantRunner`` over ``ContainerSandboxRunner`` (one hardened throw-away
container per run). Prints whether the two kill matrices are identical and the wall time
of each, and samples ``docker stats`` of the sandbox containers it started. It only ever
looks at containers whose name starts with ``radius-sbx-``.

    RADIUS_MUTATION_ALLOW_LOCAL=1 python scripts/mutation_sandbox_compare.py 08 \
        --image radius-sandbox-test:latest --json cmp.json

Fixture sanity, not a research result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EVAL = _load("mutation_wired_eval_mod", "mutation_wired_eval.py")
RUN = EVAL.RUN


def matrix(m: Any) -> dict[str, Any]:
    """Comparable, order-independent view of a Measurement."""

    return {
        "status": m.status,
        "reason": m.reason,
        "baseline_failed": sorted(m.baseline_failed),
        "baseline_flaky": sorted(m.baseline_flaky),
        "mutants": {
            r.mutant_id: {
                "op": r.operator,
                "at": f"{r.path}:{r.line}",
                "status": r.status,
                "killed_by": sorted(r.killed_by),
            }
            for r in m.mutants
        },
    }


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    out = []
    for key in ("status", "reason", "baseline_failed", "baseline_flaky"):
        if a[key] != b[key]:
            out.append(f"{key}: local={a[key]!r} sandbox={b[key]!r}")
    for mid in sorted(set(a["mutants"]) | set(b["mutants"])):
        x, y = a["mutants"].get(mid), b["mutants"].get(mid)
        if x != y:
            out.append(f"mutant {mid}: local={x} sandbox={y}")
    return out


def _mib(text: str) -> float:
    text = text.strip()
    for unit, scale in (("GiB", 1024.0), ("MiB", 1.0), ("KiB", 1 / 1024), ("B", 1 / 1048576)):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * scale
    return 0.0


class StatsPoller(threading.Thread):
    """Samples ``docker stats`` of radius-sbx-* containers only."""

    def __init__(self, runtime: str = "docker", interval: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.runtime, self.interval = runtime, interval
        self.stop = threading.Event()
        self.samples: list[tuple[float, float]] = []  # (cpu percent, mem MiB)

    def run(self) -> None:
        fmt = "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"
        while not self.stop.is_set():
            try:
                names = subprocess.run(  # noqa: S603
                    [self.runtime, "ps", "--filter", "name=radius-sbx-", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=15, check=False,
                ).stdout.split()
                if names:
                    rows = subprocess.run(  # noqa: S603
                        [self.runtime, "stats", "--no-stream", "--format", fmt, *names],
                        capture_output=True, text=True, timeout=20, check=False,
                    ).stdout.splitlines()
                    for row in rows:
                        _, cpu, mem = row.split("|")
                        self.samples.append((float(cpu.strip("%")), _mib(mem.split("/")[0])))
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            self.stop.wait(self.interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixture")
    ap.add_argument("--mode", choices=("gold", "auto"), default="gold")
    ap.add_argument("--image", default="radius-sandbox-test:latest")
    ap.add_argument("--max-mutants", type=int, default=50)
    ap.add_argument("--wall-clock", type=float, default=1800.0)
    ap.add_argument("--mutant-timeout", type=float, default=60.0)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    if os.environ.get("RADIUS_MUTATION_ALLOW_LOCAL") != "1":
        raise SystemExit("set RADIUS_MUTATION_ALLOW_LOCAL=1 (trusted F-14 fixtures only)")

    from radius_testing.infrastructure import ContainerSandboxRunner
    from radius_testing.infrastructure.sandbox_runner import SandboxConfig
    from radius_testing.mutation import (
        MeasureConfig,
        MutationBudget,
        SandboxMutantRunner,
        SubprocessLocalRunner,
        measure_mutation,
    )
    from radius_worker.verdict_v2.mutation import select_targets, unmeasured_input

    captured: dict[str, Any] = {}

    def capture(req: Any) -> Any:
        captured["req"] = req
        return unmeasured_input("capture_only")

    path = RUN.fixture_dirs([args.fixture])[0]
    RUN.run_collect(path, args.mode, "static", mutation=capture)
    req = captured["req"]
    targets = select_targets(req)
    cfg = MeasureConfig(
        budget=MutationBudget(
            max_mutants=args.max_mutants,
            wall_clock_seconds=args.wall_clock,
            per_mutant_timeout_seconds=args.mutant_timeout,
        )
    )

    t0 = time.monotonic()
    with SubprocessLocalRunner(req.repository_path) as local:
        m_local = measure_mutation(
            local, req.repository_path, targets, cfg, allow_local_runner=True
        )
    t_local = time.monotonic() - t0

    sandbox = ContainerSandboxRunner(SandboxConfig(image=args.image))
    sandbox.check_ready()
    poller = StatsPoller(sandbox.config.runtime)
    poller.start()
    t0 = time.monotonic()
    m_sandbox = measure_mutation(
        SandboxMutantRunner(req.repository_path, sandbox), req.repository_path, targets, cfg
    )
    t_sandbox = time.monotonic() - t0
    poller.stop.set()
    poller.join(timeout=30)

    a, b = matrix(m_local), matrix(m_sandbox)
    differences = diff(a, b)
    cpu = [s[0] for s in poller.samples]
    mem = [s[1] for s in poller.samples]
    report = {
        "fixture": path.name,
        "mode": args.mode,
        "image": args.image,
        "targets": [t.symbol_id for t in targets],
        "local": {
            "seconds": round(t_local, 1), "status": m_local.status, "reason": m_local.reason,
            "generated": m_local.generated, "sampled": m_local.sampled,
            "killed": sum(1 for r in m_local.mutants if r.status == "killed"),
        },
        "sandbox": {
            "seconds": round(t_sandbox, 1), "status": m_sandbox.status,
            "reason": m_sandbox.reason, "stats_samples": len(poller.samples),
            "max_cpu_percent": max(cpu, default=None),
            "max_mem_mib": round(max(mem), 1) if mem else None,
        },
        "identical": not differences,
        "differences": differences,
        "matrix_local": a,
        "matrix_sandbox": b,
    }
    print(json.dumps({k: v for k, v in report.items() if not k.startswith("matrix")}, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
        )
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
