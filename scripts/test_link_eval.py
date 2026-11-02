#!/usr/bin/env python3
"""Symbol-to-test link evaluation on the in-repo intent fixtures (LK-03).

For every fixture under ``benchmarks/fixtures/intent`` this script

1. extracts the changed symbols (LK-01) from ``base`` -> ``head`` + ``pr.patch``;
2. runs the static and naming linkers on the ``head`` sources;
3. runs the dynamic coverage-context linker inside the F-07 sandbox;
4. measures *dynamic ground truth*: every test file is executed in the sandbox
   under an independent ``sys.settrace`` tracer (no coverage.py involved) and a
   test "covers" a symbol when it executes one of the symbol's lines (the same
   idea as F-08's ``test_symbol_impact_ground_truth``, per test function);
5. reports precision/recall of the tests each linker (and the combiner, and an
   ablation) would select, against that truth and against the hand-labelled
   ``links`` of ``expected.json``.

THE NUMBERS ARE A FIXTURE SANITY CHECK, NOT A RESEARCH RESULT (LK-07 owns the
real evaluation on the gold set). Eight tiny fixtures say nothing about
generalisation.

Everything that executes repository code runs inside the hardened sandbox
(``ContainerSandboxRunner``: network disabled, read-only root, limits). If the
sandbox or an image with ``pytest`` + ``coverage`` is unavailable the script exits
with instructions; ``--host-trusted`` explicitly opts in to running the *in-repo,
reviewed* fixtures in a local subprocess for the ground truth only (the dynamic
linker never runs on the host).

Usage::

    python scripts/test_link_eval.py [--image radius-sandbox-cov:latest]
        [--json out.json] [--min-score 0.3] [--only 01_correct_strong_tests]
        [--host-trusted]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("testing", "graph", "analysis", "parser", "shared"):
    sys.path.insert(0, str(ROOT / "packages" / pkg / "src"))

from radius_analysis.symbol_changes import (  # noqa: E402
    DirectorySnapshot,
    extract_symbol_changes,
)
from radius_testing.domain.entities import TestRunPlan  # noqa: E402
from radius_testing.infrastructure import ContainerSandboxRunner, SandboxConfig  # noqa: E402
from radius_testing.linking import (  # noqa: E402
    DynamicCoverageLinker,
    LinkSet,
    LinkTarget,
    NamingLinker,
    StaticLinker,
    combine_links,
    links_from_coverage,
)
from radius_testing.linking.coveragedb import CoverageData  # noqa: E402
from radius_testing.linking.evaluation import LABEL, Prf, prf, select_tests  # noqa: E402
from radius_testing.linking.model import is_test_path, normalize_test_id  # noqa: E402

FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
DEFAULT_IMAGE = os.environ.get("RADIUS_SANDBOX_COV_IMAGE", "radius-sandbox-cov:latest")

TRACE_DRIVER = """
import json, os, sys
out, *files = sys.argv[1:]
import pytest
root = os.path.realpath(os.getcwd())
state = {"cur": None}
hits = {}
inside = {}
def local(frame, event, arg):
    if event == "line" and state["cur"] is not None:
        hits.setdefault(state["cur"], {}).setdefault(inside[frame.f_code.co_filename], set()).add(frame.f_lineno)
    return local
def trace(frame, event, arg):
    fn = frame.f_code.co_filename
    rel = inside.get(fn)
    if rel is None:
        real = os.path.realpath(fn)
        ok = real.startswith(root + os.sep) and "site-packages" not in real
        rel = inside[fn] = os.path.relpath(real, root).replace(os.sep, "/") if ok else False
    return local if rel else None
class Ctx:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        state["cur"] = item.nodeid
        yield
        state["cur"] = None
sys.settrace(trace)
try:
    code = pytest.main(["-q", "-p", "no:cacheprovider", *files], plugins=[Ctx()])
finally:
    sys.settrace(None)
    with open(out, "w") as fh:
        json.dump({k: {f: sorted(v) for f, v in d.items()} for k, d in hits.items()}, fh)
sys.exit(int(code))
""".strip()


def read_sources(head: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(head.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".ts", ".js"} and "__pycache__" not in path.parts:
            out[path.relative_to(head).as_posix()] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return out


def changed_targets(base: Path, head: Path, patch: str) -> list[LinkTarget]:
    changes = extract_symbol_changes(DirectorySnapshot(base), DirectorySnapshot(head), patch)
    return [
        LinkTarget.from_changed_symbol(s)
        for s in changes.symbols
        if s.language == "python" and s.is_behavioral and s.new_range is not None
        and s.kind in {"function", "method", "class"} and not is_test_path(s.path)  # production symbols only
    ]


def test_files(sources: Mapping[str, str]) -> list[str]:
    return sorted(p for p in sources if p.endswith(".py") and p.rsplit("/", 1)[-1].startswith("test_"))


class Truth:
    """Executes test files under the independent tracer; inside the sandbox by default."""

    def __init__(self, runner: ContainerSandboxRunner | None, host_trusted: bool) -> None:
        self.runner = runner
        self.host_trusted = host_trusted

    def trace(self, repo: Path, files: Sequence[str]) -> CoverageData:
        if self.runner is not None:
            plan = TestRunPlan.pending(uuid4(), (), (("python", ("-c", TRACE_DRIVER, "/results/trace.json", *files)),))
            _result, artifacts = self.runner.run_collecting(plan, repo, ("trace.json",))
            raw = artifacts.get("0/trace.json")
            if raw is None:
                raise RuntimeError("sandbox produced no trace (is pytest installed in the image?)")
            return _to_coverage(json.loads(raw))
        if not self.host_trusted:
            raise RuntimeError("no sandbox available and --host-trusted not given")
        out = repo.parent / f".trace-{repo.name}.json"
        subprocess.run(  # noqa: S603 - fixed argv; in-repo reviewed fixtures only
            [sys.executable, "-c", TRACE_DRIVER, str(out), *files],
            cwd=repo, capture_output=True, timeout=300, check=False, env={k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE"))},
        )  # fmt: skip
        try:
            return _to_coverage(json.loads(out.read_text()))
        finally:
            out.unlink(missing_ok=True)


def _to_coverage(raw: Mapping[str, Mapping[str, list[int]]]) -> CoverageData:
    return CoverageData({ctx: {f: frozenset(ls) for f, ls in files.items()} for ctx, files in raw.items()})


def expected_labels(expected: Mapping, targets: Sequence[LinkTarget]) -> dict[str, set[str]]:
    by_key = {(t.path, t.entity_name): t.symbol_id for t in targets}
    out: dict[str, set[str]] = {}
    for item in expected.get("links", []):
        path, _, qual = item["symbol"].partition("::")
        sid = by_key.get((path, qual))
        if sid:
            out.setdefault(sid, set()).update(normalize_test_id(t) for t in item["tests"])
    return out


def variants(static: LinkSet, naming: LinkSet, dynamic: LinkSet | None) -> dict[str, LinkSet]:
    out = {"static": static, "naming": naming, "static+naming": combine_links(static, naming)}
    if dynamic is not None:
        out["dynamic"] = dynamic
        out["combined(all)"] = combine_links(static, naming, dynamic)
        out["without:static"] = combine_links(naming=naming, dynamic=dynamic)
        out["without:naming"] = combine_links(static=static, dynamic=dynamic)
        out["without:dynamic"] = out["static+naming"]
    return out


def evaluate_fixture(
    fixture: Path,
    truth: Truth,
    dynamic_linker: DynamicCoverageLinker | None,
    min_score: float,
) -> dict:
    base, head = fixture / "base", fixture / "head"
    patch = (fixture / "pr.patch").read_text(encoding="utf-8")
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    sources = read_sources(head)
    targets = changed_targets(base, head, patch)
    files = test_files(sources)
    result: dict = {"fixture": fixture.name, "symbols": [t.qualified_name for t in targets], "tests": len(files)}
    if not targets:
        result["note"] = "no behavioural python symbol changed"
        return result
    static = StaticLinker().link(sources, targets)
    naming = NamingLinker().link(sources, targets)
    dynamic = None
    if dynamic_linker is not None:
        dyn = dynamic_linker.link(head, files, targets)
        result["dynamic_status"] = dyn.status
        result["dynamic_notes"] = list(dyn.notes)
        dynamic = dyn.links if dyn.status in {"ok", "partial"} else None
    trace_links, _ = links_from_coverage(truth.trace(head, files), targets)
    truth_by_symbol: dict[str, set[str]] = {}
    for link in trace_links:
        truth_by_symbol.setdefault(link.symbol_id, set()).add(link.test_id)
    labels = expected_labels(expected, targets)
    sids = [t.symbol_id for t in targets]
    result["truth_tests"] = sorted({t for ts in truth_by_symbol.values() for t in ts})
    rows = {}
    for name, ls in variants(static, naming, dynamic).items():
        selected = select_tests(ls, sids, min_score=min_score)
        row = {"vs_dynamic_truth": prf(selected, result["truth_tests"]).to_dict(), "selected": sorted(selected)}
        lab = {t for s in labels.values() for t in s}
        if lab:
            row["vs_labelled"] = prf(selected, lab).to_dict()
        rows[name] = row
    result["variants"] = rows
    return result


def aggregate(results: Sequence[dict], key: str) -> dict[str, dict]:
    sums: dict[str, list[int]] = {}
    for res in results:
        for name, row in res.get("variants", {}).items():
            if key in row:
                tp, fp, fn = (row[key][k] for k in ("tp", "fp", "fn"))
                acc = sums.setdefault(name, [0, 0, 0])
                acc[0] += tp
                acc[1] += fp
                acc[2] += fn
    out = {}
    for name, (tp, fp, fn) in sums.items():
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[name] = Prf(round(precision, 3), round(recall, 3), round(f1, 3), tp, fp, fn).to_dict()
    return out


def format_table(title: str, agg: Mapping[str, Mapping]) -> str:
    lines = [title, f"  {'variant':<18}{'precision':>10}{'recall':>9}{'f1':>7}{'tp':>5}{'fp':>5}{'fn':>5}"]
    for name, row in agg.items():
        lines.append(
            f"  {name:<18}{row['precision']:>10.3f}{row['recall']:>9.3f}{row['f1']:>7.3f}{row['tp']:>5}{row['fp']:>5}{row['fn']:>5}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="sandbox image with pytest + coverage")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--json", type=Path)
    parser.add_argument("--host-trusted", action="store_true", help="run ground truth for in-repo fixtures without the sandbox")
    args = parser.parse_args(argv)

    runner: ContainerSandboxRunner | None = ContainerSandboxRunner(SandboxConfig(image=args.image, timeout_seconds=args.timeout))
    try:
        runner.check_ready()  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        print(f"sandbox unavailable ({exc}).", file=sys.stderr)
        runner = None
        if not args.host_trusted:
            print(
                "Build an image: printf 'FROM radius-sandbox-test:latest\\nRUN pip install coverage' | docker build -t "
                f"{DEFAULT_IMAGE} -   (or pass --host-trusted for the ground truth only)",
                file=sys.stderr,
            )
            return 2
    truth = Truth(runner, args.host_trusted)
    dynamic = DynamicCoverageLinker(runner, enabled=True) if runner is not None else None

    results = []
    for fixture in sorted(p for p in FIXTURES.iterdir() if (p / "expected.json").is_file()):
        if args.only and fixture.name not in args.only:
            continue
        try:
            results.append(evaluate_fixture(fixture, truth, dynamic, args.min_score))
        except Exception as exc:  # noqa: BLE001 - report and continue
            results.append({"fixture": fixture.name, "error": f"{exc.__class__.__name__}: {exc}"})
    report = {
        "label": LABEL,
        "min_score": args.min_score,
        "ground_truth": "per-test sys.settrace line execution inside the sandbox" if runner else "host-trusted subprocess (in-repo fixtures)",
        "fixtures": results,
        "aggregate_vs_dynamic_truth": aggregate(results, "vs_dynamic_truth"),
        "aggregate_vs_labelled": aggregate(results, "vs_labelled"),
    }
    print(f"== Symbol->test link evaluation ({LABEL}) ==")
    print(f"threshold {args.min_score}; ground truth: {report['ground_truth']}; fixtures: {len(results)}")
    for res in results:
        status = res.get("error") or res.get("note") or f"{len(res['symbols'])} symbol(s), {res['tests']} test file(s)"
        print(f"  {res['fixture']}: {status}")
    print(format_table("\nvs dynamic ground truth (micro-averaged):", report["aggregate_vs_dynamic_truth"]))
    print(format_table("\nvs hand-labelled expected.json links (micro-averaged):", report["aggregate_vs_labelled"]))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
