"""F-08: symbol-level selection versus dynamic-execution ground truth.

Ground truth is measured, not assumed: every test file is executed in its own
subprocess under ``sys.settrace`` and a test "covers" the change when it
executes a changed line. The property under test is

    ground truth  <=  symbol-level selection  <=  file-level selection

(the right-hand inequality holds except where the dynamic-code fallback
deliberately widens the selection, see ``test_dynamic_import_widens_selection``).
"""

from __future__ import annotations

import difflib
import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import StartAnalysisCommand
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    UnifiedDiffChangeAnalyzer,
)
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_graph.application import GraphApplicationService
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
    SubprocessTestRunner,
)
from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)

HARNESS = '''
import json, os, sys, importlib
repo = os.path.realpath(sys.argv[1]); test_file = sys.argv[2]; mode = sys.argv[3]
os.chdir(repo); sys.path.insert(0, repo)
executed = set()
def local(frame, event, arg):
    if event == "line":
        executed.add((frame.f_code.co_filename, frame.f_lineno))
    return local
inside = {}
def trace(frame, event, arg):
    fn = frame.f_code.co_filename
    hit = inside.get(fn)
    if hit is None:
        hit = inside[fn] = os.path.realpath(fn).startswith(repo)
    return local if hit else None
sys.settrace(trace)
if mode == "pytest":
    import pytest
    pytest.main(["-q", "-p", "no:cacheprovider", test_file])
else:
    name = test_file[:-3].replace("/", ".")
    sys.path.insert(0, os.path.join(repo, "tests"))
    module = importlib.import_module(os.path.basename(name))
    for attr in sorted(dir(module)):
        if attr.startswith("test_"):
            getattr(module, attr)()
sys.settrace(None)
rel = sorted({(os.path.relpath(os.path.realpath(f), repo).replace(os.sep, "/"), n) for f, n in executed})
print("RESULT" + json.dumps(rel))
'''


# --------------------------------------------------------------------- helpers
def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")


def _diff(path: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        f"a/{path}",
        f"b/{path}",
        n=0,
    )
    return f"diff --git a/{path} b/{path}\n" + "".join(lines)


def _changed_lines(diff_text: str) -> set[int]:
    from radius_analysis.diff_hunks import parse_diff_modified_lines

    return next(iter(parse_diff_modified_lines(diff_text).values()))


def _select(repo: Path, diff_text: str, *, symbol: bool):
    analysis_store = InMemoryAnalysisStore()
    graph_store = InMemoryGraphStore()
    test_store = InMemoryTestStore()
    analysis_service = AnalysisApplicationService(
        analysis_store, change_analyzer=UnifiedDiffChangeAnalyzer()
    )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(uuid4(), uuid4(), "a" * 40)
    )
    orchestrator = Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(), default_language_parser_registry()
        ),
        graph_service=GraphApplicationService(graph_store),
        graph_store=graph_store,
        testing_service=TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=test_store,
            planner=StaticTestCommandPlanner(),
            runner=SubprocessTestRunner(),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(), store=InMemoryConfidenceStore()
        ),
        execute_tests=False,
        symbol_impact_enabled=symbol,
    )
    orchestrator.execute(
        ExecuteAnalysisCommand(
            analysis_id=analysis.id,
            repository_id=analysis.repository_id,
            repository_path=repo,
            diff_text=diff_text,
        )
    )
    selection = test_store.get_selection(analysis.id)
    selected = {item.test_case.path.value for item in selection.selected_tests}
    return selected, selection


def _truth(repo: Path, tests: list[str], changed_path: str, lines: set[int], mode: str) -> set[str]:
    """Tests that execute any changed line of ``changed_path``."""

    harness = repo.parent / f"{repo.name}_harness.py"
    harness.write_text(HARNESS, encoding="utf-8")
    covering: set[str] = set()
    for test in tests:
        done = subprocess.run(
            [sys.executable, "-I", str(harness), str(repo), test, mode],
            capture_output=True, text=True, cwd=repo, timeout=120, check=False,
        )
        out = [ln for ln in done.stdout.splitlines() if ln.startswith("RESULT")]
        assert out, f"harness failed for {test}: {done.stderr[-800:]}"
        executed = {(p, n) for p, n in json.loads(out[-1][len("RESULT"):])}
        if any((changed_path, n) in executed for n in lines):
            covering.add(test)
    return covering


def _scenario(tmp_path: Path, files: dict[str, str], path: str, old: str, new: str, mode="direct"):
    repo = tmp_path / "repo"
    _write(repo, files)
    head = (repo / path).read_text(encoding="utf-8")
    base = head.replace(new, old, 1)
    assert base != head, "mutation must change the head file"
    diff = _diff(path, base, head)
    tests = sorted(
        p.relative_to(repo).as_posix() for p in (repo / "tests").glob("test_*.py")
    )
    truth = _truth(repo, tests, path, _changed_lines(diff), mode)
    file_level, _ = _select(repo, diff, symbol=False)
    symbol_level, selection = _select(repo, diff, symbol=True)
    return truth, file_level, symbol_level, selection


# ----------------------------------------------------------------- scenarios
def test_shared_file_selection_is_a_strict_subset_and_covers_truth(tmp_path: Path) -> None:
    truth, file_level, symbol_level, selection = _scenario(
        tmp_path,
        {
            "src/lib.py": "def used():\n    return 11\n\n\ndef unused():\n    return 2\n",
            "tests/test_a.py": "from src.lib import used\n\n\ndef test_a():\n    assert used()\n",
            "tests/test_b.py": "from src.lib import unused\n\n\ndef test_b():\n    assert unused()\n",
        },
        "src/lib.py", "return 1\n", "return 11\n",
    )
    assert truth == {"tests/test_a.py"}
    assert truth <= symbol_level < file_level
    reasons = {d.test_case.path.value: d.reason for d in selection.decisions}
    assert "src/lib.py::used" in reasons["tests/test_a.py"]
    assert "SYMBOL_IMPACT" in {
        s for d in selection.decisions for s in d.evidence_sources
    }


def test_indirect_call_chain_across_files(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/core.py": "def deep():\n    return 21\n\n\ndef side():\n    return 0\n",
            "src/mid.py": "from src.core import deep, side\n\n\ndef wrap():\n    return deep()\n\n\ndef other():\n    return side()\n",
            "tests/test_wrap.py": "from src.mid import wrap\n\n\ndef test_w():\n    assert wrap()\n",
            "tests/test_other.py": "from src.mid import other\n\n\ndef test_o():\n    assert other() == 0\n",
        },
        "src/core.py", "return 2\n", "return 21\n",
    )
    assert truth == {"tests/test_wrap.py"}
    assert truth <= symbol_level < file_level


def test_class_methods_and_inheritance(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/base.py": "class Base:\n    def run(self):\n        return 31\n\n    def stop(self):\n        return 0\n",
            "src/derived.py": "from src.base import Base\n\n\nclass Derived(Base):\n    pass\n",
            "tests/test_derived.py": "from src.derived import Derived\n\n\ndef test_d():\n    assert Derived().run()\n",
            "tests/test_stop.py": "from src.derived import Derived\n\n\ndef test_s():\n    assert Derived().stop() == 0\n",
        },
        "src/base.py", "return 3\n", "return 31\n",
    )
    assert truth == {"tests/test_derived.py"}
    assert truth <= symbol_level < file_level


def test_decorator_change_reaches_decorated_function(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/deco.py": "def twice(fn):\n    def inner():\n        return fn() * 2 + 1\n    return inner\n\n\ndef plain(fn):\n    return fn\n",
            "src/feat.py": "from src.deco import twice, plain\n\n\n@twice\ndef a():\n    return 1\n\n\n@plain\ndef b():\n    return 1\n",
            "tests/test_a.py": "from src.feat import a\n\n\ndef test_a():\n    assert a()\n",
            "tests/test_b.py": "from src.feat import b\n\n\ndef test_b():\n    assert b()\n",
        },
        "src/deco.py", "fn() * 2\n", "fn() * 2 + 1\n",
    )
    assert truth == {"tests/test_a.py"}
    assert truth <= symbol_level


def test_reexport_through_package_init_with_alias(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.impl import real as exported\n",
            "pkg/impl.py": "def real():\n    return 41\n\n\ndef spare():\n    return 0\n",
            "tests/test_use.py": "from pkg import exported\n\n\ndef test_u():\n    assert exported()\n",
        },
        "pkg/impl.py", "return 4\n", "return 41\n",
    )
    assert truth == {"tests/test_use.py"}
    assert truth <= symbol_level


def test_callback_registry_defined_at_module_level(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/handlers.py": "def on_event():\n    return 51\n",
            "src/registry.py": "from src.handlers import on_event\n\nHANDLERS = {'e': on_event}\n\n\ndef dispatch(name):\n    return HANDLERS[name]()\n",
            "tests/test_dispatch.py": "from src.registry import dispatch\n\n\ndef test_d():\n    assert dispatch('e')\n",
        },
        "src/handlers.py", "return 5\n", "return 51\n",
    )
    assert truth == {"tests/test_dispatch.py"}
    assert truth <= symbol_level


def test_pytest_fixture_injected_by_parameter_name(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/lib.py": "def build():\n    return 61\n\n\ndef other():\n    return 0\n",
            "tests/test_fx.py": (
                "import pytest\nfrom src.lib import build\n\n\n@pytest.fixture\n"
                "def thing():\n    return build()\n\n\ndef test_it(thing):\n    assert thing\n"
            ),
            "tests/test_plain.py": "from src.lib import other\n\n\ndef test_p():\n    assert other() == 0\n",
        },
        "src/lib.py", "return 6\n", "return 61\n",
        mode="pytest",
    )
    assert truth == {"tests/test_fx.py"}
    assert truth <= symbol_level < file_level


def test_module_level_change_falls_back_to_file_level(tmp_path: Path) -> None:
    truth, file_level, symbol_level, selection = _scenario(
        tmp_path,
        {
            "src/cfg.py": "LIMIT = 71\n\n\ndef limit():\n    return LIMIT\n\n\ndef other():\n    return 0\n",
            "tests/test_limit.py": "from src.cfg import limit\n\n\ndef test_l():\n    assert limit() == 71\n",
            "tests/test_other.py": "from src.cfg import other\n\n\ndef test_o():\n    assert other() == 0\n",
        },
        "src/cfg.py", "LIMIT = 7\n", "LIMIT = 71\n",
    )
    assert symbol_level == file_level >= truth
    assert any(
        "file-level fallback" in detail
        for d in selection.decisions
        for detail in d.evidence_details
    )


def test_dynamic_import_widens_selection(tmp_path: Path) -> None:
    truth, file_level, symbol_level, _ = _scenario(
        tmp_path,
        {
            "src/plugin.py": "def run():\n    return 81\n",
            "tests/test_dyn.py": (
                "import importlib\n\n\ndef test_d():\n    name = 'src.' + 'plugin'\n"
                "    assert importlib.import_module(name).run()\n"
            ),
            "tests/test_none.py": "def test_n():\n    assert True\n",
        },
        "src/plugin.py", "return 8\n", "return 81\n",
    )
    assert truth == {"tests/test_dyn.py"}
    assert truth <= symbol_level  # file-level alone misses this test


# ------------------------------------------------------------ property test
def _random_repo(rng: random.Random, root: Path) -> tuple[str, str, str]:
    """Write a random call graph; return (changed path, old line, new line)."""

    modules = [f"m{i}" for i in range(4)]
    funcs = {m: [f"f{m[1:]}_{j}" for j in range(3)] for m in modules}
    order = [(m, f) for m in modules for f in funcs[m]]
    bodies: dict[str, list[str]] = {m: [] for m in modules}
    imports: dict[str, set[str]] = {m: set() for m in modules}
    for idx, (m, f) in enumerate(order):
        callees = rng.sample(order[:idx], k=min(idx, rng.randint(0, 2)))
        calls = []
        for cm, cf in callees:
            if cm == m:
                calls.append(f"{cf}()")
                continue
            style = rng.choice(["from", "alias", "module"])
            if style == "from":
                imports[m].add(f"from pkg.{cm} import {cf}")
                calls.append(f"{cf}()")
            elif style == "alias":
                imports[m].add(f"from pkg.{cm} import {cf} as {cf}_x")
                calls.append(f"{cf}_x()")
            else:
                imports[m].add(f"import pkg.{cm} as {cm}_mod")
                calls.append(f"{cm}_mod.{cf}()")
        expr = " + ".join(["1", *calls])
        bodies[m].append(f"def {f}():\n    return {expr}  # body\n")
    for m in modules:
        text = "\n".join(sorted(imports[m])) + "\n\n\n" + "\n\n".join(bodies[m])
        (root / "pkg" / f"{m}.py").parent.mkdir(parents=True, exist_ok=True)
        (root / "pkg" / f"{m}.py").write_text(text, encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    for t in range(4):
        picks = rng.sample(order, k=rng.randint(1, 2))
        lines = []
        for k, (m, f) in enumerate(picks):
            lines.append(f"from pkg.{m} import {f} as g{k}")
        body = "\n".join(f"    assert g{k}()" for k in range(len(picks)))
        (root / "tests" / f"test_r{t}.py").write_text(
            "\n".join(lines) + f"\n\n\ndef test_r{t}():\n{body}\n", encoding="utf-8"
        )
    target_m, target_f = rng.choice(order)
    return f"pkg/{target_m}.py", target_f, "return 1 +"


@pytest.mark.parametrize("seed", range(8))
def test_random_call_graphs_never_drop_a_covering_test(tmp_path: Path, seed: int) -> None:
    rng = random.Random(seed)
    repo = tmp_path / "repo"
    repo.mkdir()
    path, func, _ = _random_repo(rng, repo)
    head = (repo / path).read_text(encoding="utf-8")
    lines = head.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"def {func}("))
    base_lines = list(lines)
    base_lines[start + 1] = base_lines[start + 1].replace("return 1", "return 0", 1)
    diff = _diff(path, "".join(base_lines), head)
    tests = sorted(p.relative_to(repo).as_posix() for p in (repo / "tests").glob("test_*.py"))
    truth = _truth(repo, tests, path, _changed_lines(diff), "direct")
    file_level, _ = _select(repo, diff, symbol=False)
    symbol_level, _ = _select(repo, diff, symbol=True)
    assert truth <= file_level, "file-level baseline itself misses a covering test"
    assert truth <= symbol_level, f"dropped covering tests: {sorted(truth - symbol_level)}"
    assert symbol_level <= file_level
