#!/usr/bin/env python
"""Run the demo repository's three PR scenarios through the real Radius pipeline, offline.

    DATABASE_URL=postgresql+psycopg://radius:radius@localhost:5432/radius \
        python scripts/demo_verify.py            # A, B and C, one process each
    python scripts/demo_verify.py --scenario B   # one scenario

It reuses ``scripts/smoke_e2e.py`` (real migrations, API, worker, Verdict v2 and GitHub client
against an in-memory fake GitHub) but swaps in the repository built by ``scripts/demo_repo.py`` and
a JUnit report produced by REALLY running pytest on the PR branch (not the fixture's recorded
outcomes). It prints, per scenario, what the pipeline actually produced: the verdict before and
after CI results, the deciding rule, per-criterion states, the Check Run conclusion and the PR
comment text. It does not assert the expectations in ``demo/EXPECTED.md``; it reports observed
versus expected so a mismatch is visible instead of hidden.

The same throw-away database rules as the smoke apply: a ``radius_smoke_<random>`` database is
created next to ``DATABASE_URL`` and dropped. This is a fake-GitHub rehearsal: it is also the
FALLBACK for the live demo (see docs/DEMO_RUNBOOK.md).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_scenario(key: str, base_url: str) -> dict:
    smoke_e2e = _load("smoke_e2e")
    demo_repo = _load("demo_repo")
    scenario = next(s for s in demo_repo.SCENARIOS if s.key == key)
    state: dict = {}
    keep_db = os.environ.get("RADIUS_SMOKE_KEEP_DB") == "1"  # read now: setup() scrubs RADIUS_*

    def fake_intent_spec(_expected):
        return demo_repo.combined_intent_spec((scenario,))

    def fake_build_origin(path, _spec, _source=None):
        shas = demo_repo.build_work_repo(path)
        demo_repo.git(["branch", "feature", scenario.branch], path)
        # the harness opens its PR against "main": make main the scenario's base branch
        demo_repo.git(["checkout", "-q", scenario.base_branch], path)
        demo_repo.git(["branch", "-f", "main", scenario.base_branch], path)
        demo_repo.git(["checkout", "-q", "main"], path)
        state["origin"] = path
        return shas[scenario.base_branch], shas[scenario.branch]

    def real_junit(_outcomes):
        # Really run pytest on the PR branch checkout, like scripts/radius_ci.py run does.
        with tempfile.TemporaryDirectory(prefix="demo-verify-") as tmp:
            checkout = Path(tmp) / "checkout"
            subprocess.run(  # noqa: S603, S607
                ["git", "clone", "-q", "--branch", scenario.branch, str(state["origin"]), str(checkout)],
                check=True, capture_output=True,
            )
            junit = Path(tmp) / "junit.xml"
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                 f"--junitxml={junit}"],
                cwd=checkout, check=False, capture_output=True,
            )
            state["junit"] = junit.read_text(encoding="utf-8")
            return junit.read_bytes()

    smoke_e2e.intent_spec = fake_intent_spec
    smoke_e2e.build_origin_repo = fake_build_origin
    smoke_e2e.junit_from_outcomes = real_junit

    fixture_no = scenario.fixture[:2]

    class DemoSmoke(smoke_e2e.Smoke):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.full = False  # uniform verdict flow; sections extraction like the default .env

        def setup(self):
            super().setup()
            self.github.title = scenario.title
            self.github.pr_body = scenario.body

        def compare_with_expectations(self, payload):
            self.observed.setdefault("stages", []).append({
                "stage": "after_ci" if "after_ci" not in {s["stage"] for s in self.observed.get("stages", [])} else "after_confirm",
                "verdict": payload["verdict"],
                "decided_by": payload["justification"]["decided_by"],
                "revision": payload["revision"],
                "criteria": [{"text": c["text"], "state": c["state"], "S": c.get("S"),
                              "flags": c["flags"]} for c in payload["criteria"]],
                "check_run_conclusion": self.github.check_runs[0].get("conclusion"),
                "check_run_title": self.github.check_runs[0]["output"]["title"],
                "check_run_details_url": self.github.check_runs[0].get("details_url"),
                "comment": self.github.comments[0]["body"],
            })

    workdir = Path(tempfile.mkdtemp(prefix="demo-verify-"))
    database_url, name = smoke_e2e.create_database(base_url)
    smoke = DemoSmoke(workdir, database_url, fixture_no)
    ok = False
    try:
        smoke.setup()
        smoke.health_and_auth()
        smoke.verdict_flow()
        ok = True
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        smoke.observed["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        smoke.finish()
        if keep_db:
            print(f"kept database {name} (scenario {key}); drop it when done", file=sys.stderr)
        else:
            smoke_e2e.drop_database(base_url, name)
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
    return {
        "scenario": key, "branch": scenario.branch, "ok": ok,
        "expected": scenario.expected_verdict, "expected_rule": scenario.expected_rule,
        "verdict_before_ci": smoke.observed.get("verdict_before_ci"),
        "stages": smoke.observed.get("stages", []),
        "junit_testcases": state.get("junit", "").count("<testcase"),
        "error": smoke.observed.get("error"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--scenario", choices=["A", "B", "C"])
    parser.add_argument("--json-out")
    parser.add_argument("--show-comment", action="store_true", help="print the PR comment text")
    args = parser.parse_args(argv)
    base_url = os.environ.get("DATABASE_URL", "")
    if not base_url:
        print("DATABASE_URL is required (PostgreSQL, a throw-away server)", file=sys.stderr)
        return 2
    smoke_e2e = _load("smoke_e2e")
    for entry in reversed(smoke_e2e._pythonpath()):  # noqa: SLF001
        path = str(ROOT / entry)
        if path not in sys.path:
            sys.path.insert(0, path)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    os.chdir(ROOT)

    if args.scenario:
        result = run_scenario(args.scenario, base_url)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        return 0 if result["ok"] else 1

    results = []
    for key in ("A", "B", "C"):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            out = handle.name
        started = time.monotonic()
        subprocess.run(  # noqa: S603 - fixed argv, fresh interpreter per scenario
            [sys.executable, str(Path(__file__).resolve()), "--scenario", key, "--json-out", out],
            env=os.environ.copy(), check=False,
        )
        try:
            result = json.loads(Path(out).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {"scenario": key, "ok": False, "error": "no result written", "stages": []}
        Path(out).unlink(missing_ok=True)
        result["seconds"] = round(time.monotonic() - started, 1)
        results.append(result)

    print("\nPR  branch                 expected               before CI              after CI (rule)        check run")
    for r in results:
        stage = (r.get("stages") or [{}])[0]
        print(f"{r['scenario']:<4}{r.get('branch', ''):<23}{r.get('expected', ''):<23}"
              f"{str(r.get('verdict_before_ci')):<23}"
              f"{stage.get('verdict', '?')} ({stage.get('decided_by', '?')})".ljust(23 * 4 + 4)
              + f"  {stage.get('check_run_conclusion', '?')}"
              + ("" if r["ok"] else f"   RUN PROBLEM: {r.get('error')}"))
        if args.show_comment and stage:
            print("\n" + stage["comment"] + "\n")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
