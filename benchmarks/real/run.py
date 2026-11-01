"""Real-code mutation benchmark for Radius (extends benchmarks/scenarios/harness.py).

Each subject is one Radius package copied into a fresh scratch git repo (pinned to the
source repo SHA). Every scenario (seeded AST mutant or structural change) is a commit on its
own branch so Radius analyses ``main...HEAD`` like a PR, through the same local orchestrator
wiring harness.py uses (real parser, graph, selection, SubprocessTestRunner, scorer).

    python benchmarks/real/run.py --subjects parser graph confidence testing --mutants 30 --seed 1

Ground truth = full-suite outcome on the scenario commit (set of failing test files),
computed independently of Radius; failing suites are re-run once to flag flakiness.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(REPO / "benchmarks" / "scenarios")]
_cfg = tomllib.loads((REPO / "pyproject.toml").read_text())
sys.path[2:2] = [str(REPO / p) for p in _cfg["tool"]["pytest"]["ini_options"]["pythonpath"]]

import mutations  # noqa: E402
from harness import _git  # noqa: E402  (reuse harness git helper)

# subject -> (package dir, read-only sibling package src dirs needed by its imports)
SUBJECTS = {
    "parser": ("packages/parser", ["packages/shared/src"]),
    "graph": ("packages/graph", ["packages/parser/src", "packages/shared/src"]),
    "confidence": ("packages/confidence", ["packages/testing/src", "packages/shared/src"]),
    "testing": ("packages/testing", ["packages/shared/src"]),
}
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
          "--import-mode=importlib", "-rfE"]
TEST_CMD = "python -m pytest -q -p no:cacheprovider -o addopts= --import-mode=importlib tests"


def run_tests(root: Path, files: list[str] | None = None) -> tuple[list[str], int, float]:
    """Run pytest; return (sorted failing/erroring test files, exit code, seconds)."""
    t = time.monotonic()
    p = subprocess.run([*PYTEST, *(files or ["tests"])], cwd=root, capture_output=True, text=True,
                       timeout=600)
    fails = set()
    for ln in p.stdout.splitlines():
        if ln.startswith(("FAILED ", "ERROR ")):
            fails.add(ln.split()[1].split("::")[0])
    if p.returncode not in (0, 1, 5) and not fails:  # collection/usage error: whole selection
        fails = set(files or ["<collection-error>"])
    return sorted(fails), p.returncode, time.monotonic() - t


def radius(root: Path, diff: str) -> dict:
    """Run the real Radius pipeline exactly as harness.run_scenario does."""
    from radius_analysis.domain import Analysis, AnalysisStatus, CommitSha
    from radius_worker.orchestrator import ExecuteAnalysisCommand
    from radius_worker.runner import create_local_orchestrator

    orch = create_local_orchestrator()
    a = orch._analysis._store.save(Analysis(id=None, repository_id=uuid4(), pull_request_id=uuid4(),
                                            commit_sha=CommitSha("0" * 40), status=AnalysisStatus.PENDING))
    t = time.monotonic()
    try:
        orch.execute(ExecuteAnalysisCommand(analysis_id=a.id, repository_id=uuid4(),
                                            repository_path=root, diff_text=diff))
    except Exception as exc:  # noqa: BLE001 - benchmark records crashes
        return {"selected": [], "failing": [], "verdict": "crashed", "score": None,
                "run": f"crash:{exc.__class__.__name__}", "seconds": time.monotonic() - t}
    secs = time.monotonic() - t
    ts = orch._testing._store
    selection = ts.get_selection(a.id)
    sel = sorted(i.test_case.path.value for i in selection.selected_tests)
    run = ts.get_run_result(a.id)
    rep = orch._confidence._store.get_by_analysis_id(a.id)
    status = run.status.value if run is not None else "not_run"
    # Radius' run result is aggregate; attribute failures to files by re-running only the
    # selected files (not counted in Radius wall-clock).
    fails = run_tests(root, sel)[0] if sel and status in ("failed", "error") else []
    return {"selected": sel, "failing": fails, "verdict": rep.verification_status,
            "score": rep.confidence_score.value, "run": status,
            "run_counts": None if run is None else [run.total_tests, run.passed, run.failed, run.skipped],
            "seconds": secs}


def module_of(path: str) -> str:
    return path.removeprefix("src/").removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def most_imported(srcs: dict[str, str]) -> str:
    """Source module imported by the most other source modules (the 'shared helper')."""
    mods = {module_of(p): p for p in srcs if not p.endswith("__init__.py")}
    hits: Counter[str] = Counter()
    for p, text in srcs.items():
        names = set()
        for n in ast.walk(ast.parse(text)):
            if isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module)
                names.update(f"{n.module}.{a.name}" for a in n.names)
            elif isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
        for m in names & set(mods):
            if mods[m] != p:
                hits[mods[m]] += 1
    return sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def structural(root: Path, srcs: dict[str, str], seed: int) -> list[tuple[str, str, dict]]:
    """(kind, file, apply-fn args). Applied on a fresh branch from main."""
    helper = most_imported(srcs)
    sites = mutations.candidate_sites(srcs[helper])
    site = mutations.sample({helper: srcs[helper]}, 1, seed)[0][1] if sites else None
    return [
        ("structural:shared_helper_mutation", helper, {"mutate": site}),
        ("structural:delete_imported_module", helper, {"delete": True}),
        ("structural:rename_module_no_import_update", helper, {"rename": True}),
        ("structural:manifest_change", "package.json", {"manifest": True}),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", nargs="+", default=["parser", "graph"], choices=sorted(SUBJECTS))
    ap.add_argument("--mutants", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workdir", default=None, help="parent dir for scratch repos (default: system tmp)")
    ap.add_argument("--no-structural", action="store_true")
    args = ap.parse_args()
    sha = _git(REPO, "rev-parse", "HEAD").strip()
    # Radius (the tool under test) runs from the working tree; record whether it differs from HEAD.
    tool_dirty = bool(_git(REPO, "status", "--porcelain", "--", "packages", "apps").strip())
    # Subjects and their read-only deps come from the committed tree at `sha` (git archive),
    # never from the possibly-dirty working tree.
    snap = Path(tempfile.mkdtemp(prefix="rb-snapshot-", dir=args.workdir))
    archive = subprocess.run(["git", "archive", sha, "packages"], cwd=REPO, check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(snap)], input=archive.stdout, check=True)
    out = HERE / "results"
    out.mkdir(parents=True, exist_ok=True)
    for subj in args.subjects:
        pkg, deps = SUBJECTS[subj]
        root = Path(tempfile.mkdtemp(prefix=f"rb-{subj}-", dir=args.workdir))
        shutil.copytree(snap / pkg, root, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "node_modules", "*.egg-info"))
        # Subprocesses (full suite, baseline, Radius' SubprocessTestRunner) import the subject from
        # the scratch copy only; sibling packages are read-only deps from the source checkout.
        os.environ["PYTHONPATH"] = os.pathsep.join([str(root / "src"), *(str(snap / d) for d in deps)])
        for cmd in (("init", "-q", "-b", "main"), ("config", "user.email", "bench@radius.invalid"),
                    ("config", "user.name", "bench"), ("add", "-A"), ("commit", "-qm", "base")):
            _git(root, *cmd)
        base_fail, base_rc, base_s = run_tests(root)
        tests = sorted(str(p.relative_to(root)) for p in (root / "tests").rglob("test_*.py"))
        srcs = {str(p.relative_to(root)): p.read_text() for p in sorted((root / "src").rglob("*.py"))}
        plan: list[tuple[str, str, dict]] = [
            (site.operator, path, {"mutate": site})
            for path, site in mutations.sample(srcs, args.mutants, args.seed)]
        if not args.no_structural:
            plan += structural(root, srcs, args.seed)
        rows = []
        for i, (kind, path, how) in enumerate(plan):
            _git(root, "checkout", "-q", "-f", "-B", f"s{i}", "main")
            changed = [path]
            if how.get("mutate") is not None:
                (root / path).write_text(mutations.apply(srcs[path], how["mutate"]))
            elif how.get("delete"):
                _git(root, "rm", "-q", path)
            elif how.get("rename"):
                new = path.removesuffix(".py") + "_renamed.py"
                _git(root, "mv", path, new)
                changed = [path, new]
            elif how.get("manifest"):
                data = json.loads((root / path).read_text())
                data["version"] = data.get("version", "0.0.0") + "-bench"
                (root / path).write_text(json.dumps(data, indent=2) + "\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", f"scenario {i}: {kind}")
            diff = _git(root, "diff", "main...HEAD")
            truth, truth_rc, full_s = run_tests(root)
            rerun = run_tests(root)[0] if truth else truth
            stems = {Path(c).stem for c in changed if c.endswith(".py")}
            conv = [t for t in tests if any(s and s != "__init__" and s in Path(t).stem.removeprefix("test_")
                                            for s in stems)]
            conv_fail, _, conv_s = run_tests(root, conv) if conv else ([], 0, 0.0)
            row = {"subject": subj, "id": i, "kind": kind, "file": path,
                   "line": how["mutate"].lineno if how.get("mutate") else None,
                   "truth_failing": truth, "truth_rc": truth_rc, "flaky": rerun != truth,
                   "total_test_files": len(tests),
                   "full": {"selected": tests, "failing": truth, "seconds": round(full_s, 3)},
                   "convention": {"selected": conv, "failing": conv_fail, "seconds": round(conv_s, 3)},
                   "radius": radius(root, diff)}
            row["radius"]["seconds"] = round(row["radius"]["seconds"], 3)
            rows.append(row)
            print(f"{subj} {i:>2} {kind:<40} truth={len(truth)} radius={row['radius']['verdict']}"
                  f"/{len(row['radius']['selected'])} conv={len(conv)}", flush=True)
        meta = {"subject": subj, "source_sha": sha, "tool_working_tree_dirty": tool_dirty, "package": pkg,
                "deps_readonly": deps, "seed": args.seed, "mutants_requested": args.mutants,
                "test_files": len(tests), "source_files": len(srcs), "test_command": TEST_CMD,
                "baseline_failing": base_fail, "baseline_rc": base_rc, "baseline_seconds": round(base_s, 3),
                "python": sys.version.split()[0]}
        with open(out / f"{subj}.jsonl", "w") as f:
            f.write(json.dumps({"meta": meta}) + "\n")
            for r in rows:
                f.write(json.dumps(r) + "\n")
        shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(snap, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
