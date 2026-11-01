"""Scenario benchmark for Radius' verification verdicts.

Each scenario builds a small git repository, applies a pull-request-like
change, runs the Radius pipeline (local in-memory orchestrator, real
subprocess test execution), and separately runs the *full* test suite as
ground truth.

Metrics per scenario:
* selected / discovered test files
* Radius verdict and heuristic score
* full-suite ground truth (any failure?)
* FALSE SAFETY: Radius says ``verified`` while the full suite fails
* MISSED FAILURE: the full suite fails but no failing test was selected

Run: ``python benchmarks/scenarios/harness.py`` (requires pytest importable by
the ``python`` on PATH). Results are printed as a Markdown table.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from radius_analysis.domain import Analysis, AnalysisStatus, CommitSha
from radius_worker.orchestrator import ExecuteAnalysisCommand
from radius_worker.runner import create_local_orchestrator


@dataclass(frozen=True)
class Scenario:
    name: str
    base: dict[str, str]
    change: dict[str, str] = field(default_factory=dict)
    delete: tuple[str, ...] = ()
    expect_full_suite_fails: bool | None = None


@dataclass
class ScenarioResult:
    name: str
    crashed: str | None
    selected: tuple[str, ...]
    discovered: int
    verdict: str
    score: float
    run_status: str
    full_suite_failed: bool
    seconds: float

    @property
    def false_safety(self) -> bool:
        return self.verdict == "verified" and self.full_suite_failed

    @property
    def missed_failure(self) -> bool:
        return self.full_suite_failed and self.verdict not in {"failed"}


SHOP = {
    "shop/__init__.py": "",
    "shop/pricing.py": "def total(xs):\n    return sum(xs)\n",
    "shop/cart.py": "from shop.pricing import total\n\ndef cart_total(items):\n    return total(items)\n",
    "shop/checkout.py": "from shop import cart\n\ndef checkout(items):\n    return {'due': cart.cart_total(items)}\n",
    "tests/test_checkout.py": "from shop.checkout import checkout\n\ndef test_checkout():\n    assert checkout([1, 2])['due'] == 3\n",
    "tests/test_unrelated.py": "def test_x():\n    assert True\n",
}
BUGGY_PRICING = {"shop/pricing.py": "def total(xs):\n    return sum(xs) + 1  # BUG\n"}

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("S1 transitive regression via `from pkg import mod`", SHOP, BUGGY_PRICING, expect_full_suite_fails=True),
    Scenario("S1b benign change, transitive test passes", SHOP, {"shop/pricing.py": "def total(xs):\n    return sum(list(xs))\n"}, expect_full_suite_fails=False),
    Scenario(
        "S2 TS multi-line `../` import (runner not installed)",
        {
            "src/lib/math.ts": "export function add(a: number, b: number) { return a + b; }\n",
            "src/app/calc.ts": "import {\n  add,\n} from '../lib/math';\nexport const calc = () => add(1, 2);\n",
            "src/app/calc.test.ts": "import { calc } from './calc';\n",
        },
        {"src/lib/math.ts": "export function add(a: number, b: number) { return a - b; }\n"},
    ),
    Scenario(
        "S3 changed module with no reaching test",
        {**SHOP, "shop/audit.py": "def log(x):\n    return x\n"},
        {"shop/audit.py": "def log(x):\n    return None\n"},
        expect_full_suite_fails=False,
    ),
    Scenario("S4 unrelated malformed .py in repo", {**SHOP, "scripts/broken.py": "def oops(:\n"}, BUGGY_PRICING, expect_full_suite_fails=True),
    Scenario("S5 deleted module still imported", SHOP, delete=("shop/pricing.py",), expect_full_suite_fails=True),
    Scenario("S6 dependency manifest change", {**SHOP, "requirements.txt": "requests==2.0\n"}, {"requirements.txt": "requests==1.0\n"}),
    Scenario("S7 unsupported-language change (SQL)", {**SHOP, "db/schema.sql": "create table t(id int);\n"}, {"db/schema.sql": "create table t(id bigint);\n"}),
    Scenario("S8 JS test, runner not installed", {"lib/a.js": "module.exports = 1\n", "lib/a.test.js": "require('./a')\n"}, {"lib/a.js": "module.exports = 2\n"}),
    Scenario(
        "S9 helper files under tests/",
        {**SHOP, "tests/conftest.py": "import pytest\n", "tests/fixtures/data.py": "X=1\n"},
        {"shop/pricing.py": "def total(xs):\n    return sum(xs)  # touched\n"},
    ),
    Scenario("S10 selected test file collects zero tests", {"m/__init__.py": "", "m/core.py": "def f():\n    return 1\n", "tests/test_core.py": "# no tests yet\n"}, {"m/core.py": "def f():\n    return 2\n"}),
    Scenario(
        "S11 regression; weak name-matched test passes",
        {**SHOP, "tests/test_pricing.py": "from shop.pricing import total\n\ndef test_callable():\n    assert callable(total)\n"},
        BUGGY_PRICING,
        expect_full_suite_fails=True,
    ),
    Scenario("S12 docs-only change", {**SHOP, "README.md": "# Shop\n"}, {"README.md": "# Shop\nMore docs.\n"}, expect_full_suite_fails=False),
    Scenario(
        "S13 src-layout package import",
        {
            "src/billing/__init__.py": "",
            "src/billing/tax.py": "def tax(x):\n    return x * 0.1\n",
            "src/billing/invoice.py": "from billing.tax import tax\n\ndef invoice(x):\n    return x + tax(x)\n",
            "tests/test_invoice.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'src'))\nfrom billing.invoice import invoice\n\ndef test_invoice():\n    assert invoice(10) == 11\n",
        },
        {"src/billing/tax.py": "def tax(x):\n    return x * 0.2\n"},
        expect_full_suite_fails=True,
    ),
    Scenario(
        "S14 lazy import inside function",
        {
            "app/__init__.py": "",
            "app/flags.py": "ENABLED = True\n",
            "app/feature.py": "def run():\n    from app.flags import ENABLED\n    return ENABLED\n",
            "tests/test_feature.py": "from app.feature import run\n\ndef test_run():\n    assert run() is True\n",
        },
        {"app/flags.py": "ENABLED = False\n"},
        expect_full_suite_fails=True,
    ),
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content), encoding="utf-8")


def build_repo(scenario: Scenario, root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "bench@radius.invalid")
    _git(root, "config", "user.name", "bench")
    _write(root, scenario.base)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _write(root, scenario.change)
    for rel in scenario.delete:
        (root / rel).unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "change")


def full_suite_failed(root: Path) -> bool:
    has_py_tests = any(root.rglob("test_*.py"))
    if not has_py_tests:
        return False
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode not in (0, 5)


def run_scenario(scenario: Scenario) -> ScenarioResult:
    with tempfile.TemporaryDirectory(prefix="radius-bench-") as tmp:
        root = Path(tmp)
        build_repo(scenario, root)
        diff = _git(root, "diff", "HEAD~1", "HEAD")
        orchestrator = create_local_orchestrator()
        store = orchestrator._analysis._store
        analysis = store.save(
            Analysis(
                id=None,
                repository_id=uuid4(),
                pull_request_id=uuid4(),
                commit_sha=CommitSha("0" * 40),
                status=AnalysisStatus.PENDING,
            )
        )
        started = time.monotonic()
        crashed: str | None = None
        try:
            orchestrator.execute(
                ExecuteAnalysisCommand(
                    analysis_id=analysis.id,
                    repository_id=uuid4(),
                    repository_path=root,
                    diff_text=diff,
                )
            )
        except Exception as exc:  # noqa: BLE001 - benchmark records crashes
            crashed = f"{exc.__class__.__name__}: {str(exc)[:80]}"
        seconds = time.monotonic() - started
        truth = full_suite_failed(root)
        if crashed:
            return ScenarioResult(scenario.name, crashed, (), 0, "crashed", 0.0, "-", truth, seconds)
        testing_store = orchestrator._testing._store
        selection = testing_store.get_selection(analysis.id)
        run = testing_store.get_run_result(analysis.id)
        report = orchestrator._confidence._store.get_by_analysis_id(analysis.id)
        return ScenarioResult(
            name=scenario.name,
            crashed=None,
            selected=tuple(item.test_case.path.value for item in selection.selected_tests),
            discovered=selection.total_discovered_count,
            verdict=report.verification_status,
            score=report.confidence_score.value,
            run_status=run.status.value if run is not None else "not_run",
            full_suite_failed=truth,
            seconds=seconds,
        )


def main() -> int:
    results = [run_scenario(scenario) for scenario in SCENARIOS]
    print("| Scenario | Selected / discovered | Run | Verdict | Score | Full suite | False safety |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        selected = "crash: " + r.crashed if r.crashed else f"{len(r.selected)}/{r.discovered} {list(r.selected)}"
        print(
            f"| {r.name} | {selected} | {r.run_status} | {r.verdict} | {r.score:.0f} | "
            f"{'FAIL' if r.full_suite_failed else 'pass'} | {'YES' if r.false_safety else 'no'} |"
        )
    false_safety = sum(r.false_safety for r in results)
    crashes = sum(r.crashed is not None for r in results)
    failing = [r for r in results if r.full_suite_failed]
    caught = sum(r.verdict == "failed" for r in failing)
    abstained = sum(r.verdict == "insufficient_evidence" for r in failing)
    print()
    print(f"scenarios={len(results)} crashes={crashes} false_safety={false_safety} "
          f"regressions={len(failing)} caught_as_failed={caught} abstained={abstained}")
    return 1 if false_safety or crashes else 0


if __name__ == "__main__":
    raise SystemExit(main())
