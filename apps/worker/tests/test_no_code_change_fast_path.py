"""Changes with no executable file skip parsing, the graph and test discovery."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from radius_analysis.dto import StartAnalysisCommand
from radius_worker.orchestrator import ExecuteAnalysisCommand
from radius_worker.runner import create_local_orchestrator


def _diff(*paths: str) -> str:
    return "".join(
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
        for path in paths
    )


def _repository(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "core.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_core.py").write_text(
        "from src.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path, *paths: str):
    _repository(tmp_path)
    orchestrator = create_local_orchestrator()
    orchestrator._execute_tests = False
    repository_id = uuid4()
    analysis = orchestrator._analysis.start_analysis(
        StartAnalysisCommand(
            repository_id=repository_id, pull_request_id=uuid4(), commit_sha="a" * 40
        )
    )
    result = orchestrator.execute(
        ExecuteAnalysisCommand(
            analysis_id=analysis.id,
            repository_id=repository_id,
            repository_path=tmp_path,
            diff_text=_diff(*paths),
        )
    )
    return orchestrator, analysis.id, result


class _Exploding:
    def __getattr__(self, name):
        raise AssertionError(f"the fast path must not use {name}")


def test_docs_only_change_skips_parse_graph_and_discovery(tmp_path: Path, monkeypatch) -> None:
    import radius_worker.runner as worker_runner

    real = worker_runner.create_local_orchestrator

    def without_heavy_phases(queue=None):
        orchestrator = real(queue)
        orchestrator._parser = _Exploding()
        orchestrator._graph = _Exploding()
        orchestrator._testing.discover_test_cases = _Exploding().discover
        return orchestrator

    monkeypatch.setattr(worker_runner, "create_local_orchestrator", without_heavy_phases)
    orchestrator, analysis_id, result = _run(
        tmp_path,
        "README.md",
        "docs/guide.md",
        "changelog.d/x.fixed.md",
        ".github/workflows/ci.yml",
        "LICENSE",
        "assets/logo.png",
    )

    selection = orchestrator._testing.get_selection(analysis_id)
    report = orchestrator._confidence.get_report(analysis_id)
    assert result.graph_node_count == 0 and result.selected_tests == 0
    assert selection.selected_count == 0
    assert orchestrator._graph_store.get_snapshot(analysis_id) is None
    # The three v1 states are kept: nothing executable changed, so no test evidence
    # is required, and the summary says so instead of claiming tests passed.
    assert report.verification_status == "verified"
    assert "no executable code changed" in report.summary
    assert "ran and passed" not in report.summary
    non_executable = [e.message for e in report.evidence if e.label == "non_executable_changed_file"]
    assert len(non_executable) == 6


@pytest.mark.parametrize("code_path", ["src/core.py", "docker-compose.yml"])
def test_any_other_file_takes_the_full_pipeline(tmp_path: Path, code_path: str) -> None:
    orchestrator, analysis_id, result = _run(tmp_path, "README.md", code_path)

    assert result.graph_node_count > 0
    assert orchestrator._graph_store.get_snapshot(analysis_id) is not None
    assert "no executable code changed" not in orchestrator._confidence.get_report(
        analysis_id
    ).summary
