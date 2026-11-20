"""scripts/ci/evidence_scope.py: which radius-evidence.yml suites a pull request needs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "evidence_scope", ROOT / "scripts" / "ci" / "evidence_scope.py"
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

ALL = [shard["shard"] for shard in module.SHARDS]
# What a test or script mentions: a docs file named here is not docs-only.
REFERENCED = 'DOC_PAGE = ROOT / "docs" / "evidence" / "TAMPER_RULES.md"\n'


def _decide(*paths: str) -> tuple[list[str], bool]:
    matrix, dashboard = module.decide(paths, lambda name: name in REFERENCED)
    return [shard["shard"] for shard in matrix], dashboard


def test_shards_cover_exactly_the_coverage_test_directories() -> None:
    directories: list[str] = []
    for shard in module.SHARDS:
        paths = module.rest_paths(ROOT) if shard["paths"] == "rest" else shard["paths"].split()
        directories.extend(paths)
    expected = ["apps/api/tests", "apps/worker/tests", "tests"] + [
        p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "packages").glob("*/tests"))
    ]
    assert sorted(directories) == sorted(expected)
    assert len(directories) == len(set(directories)), "a directory is in two shards"


def test_the_testing_shard_gets_the_sandbox_image() -> None:
    # radius-evidence.yml builds radius-sandbox-test only for the "testing" shard.
    shard = next(s for s in module.SHARDS if s["shard"] == "testing")
    assert "packages/testing/tests" in shard["paths"].split()
    workflow = (ROOT / ".github" / "workflows" / "radius-evidence.yml").read_text(encoding="utf-8")
    assert "if: ${{ matrix.shard == 'testing' }}" in workflow


@pytest.mark.parametrize(
    "paths",
    [
        ("docs/DEPLOYMENT_NOTES_X.md",),
        ("docs/operations/guide-x.md", "docs/img/diagram-x.png"),
        ("changelog.d/123.fixed.md", "changelog.d/README.md"),
        (),
    ],
)
def test_docs_and_changelog_only_run_nothing(paths: tuple[str, ...]) -> None:
    assert _decide(*paths) == ([], False)


@pytest.mark.parametrize(
    "path",
    [
        "docs/evidence/TAMPER_RULES.md",  # named by a test
        "docs/research/design/verdict_v2.example.08.json",  # fixture data
        "docs/research/preregistration/x.md",  # docs/research is read by tests
        "docs/api/openapi.json",  # not prose
        "README.md",
        "pyproject.toml",
        ".github/workflows/radius-evidence.yml",
        "scripts/ci/merge_node_junit.py",
        "packages/linking/src/x.py",
    ],
)
def test_anything_tests_can_read_runs_every_suite(path: str) -> None:
    assert _decide("docs/notes-x.md", path) == (ALL, True)


def test_dashboard_only_runs_the_dashboard_and_the_root_tests() -> None:
    # scripts/gen_config_reference.py scans apps/dashboard (tests/test_config_reference.py).
    shards, dashboard = _decide("apps/dashboard/lib/api.ts", "docs/notes-x.md")
    assert dashboard is True
    assert shards == sorted(module.DASHBOARD_COUPLED)
    assert any("tests" in s["paths"].split() for s in module.SHARDS if s["shard"] in shards)


def test_windows_separators_and_blank_lines_are_tolerated() -> None:
    assert _decide("", "changelog.d\\1.fixed.md", "  ") == ([], False)


def test_main_writes_github_outputs(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "packages" / "zeta" / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "testing" / "tests").mkdir(parents=True)
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")

    assert module.main(["--root", str(tmp_path), "--rest"]) == 0
    assert capsys.readouterr().out.split() == ["packages/zeta/tests"]

    monkeypatch.setattr("sys.stdin", _Stdin("docs/guide.md\n"))
    assert module.main(["--root", str(tmp_path)]) == 0
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert json.loads(lines["python-matrix"]) == [] and lines["dashboard"] == "false"

    assert module.main(["--root", str(tmp_path), "--all"]) == 0
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert [s["shard"] for s in json.loads(lines["python-matrix"])] == ALL
    assert lines["dashboard"] == "true"


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
