"""Unit tests for multi-language (Python + TypeScript) CPG extraction and slicing in Phase1AnalysisOrchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from radius_graph.slicer import GraphSlicer
from radius_worker.orchestrator import Phase1AnalysisOrchestrator


def _create_test_repository(repo_path: Path) -> None:
    """Create a temporary repository structure containing both Python and TypeScript files."""
    # Python files: service.py calling db.py
    db_py = repo_path / "db.py"
    db_py.write_text(
        "def query():\n" "    return 'database result'\n",
        encoding="utf-8",
    )

    service_py = repo_path / "service.py"
    service_py.write_text(
        "from db import query\n\n" "def handle_request():\n" "    return query()\n",
        encoding="utf-8",
    )

    # TypeScript files: handler.ts calling utils.ts
    utils_ts = repo_path / "utils.ts"
    utils_ts.write_text(
        "export function formatData(): string {\n" "    return 'formatted';\n" "}\n",
        encoding="utf-8",
    )

    handler_ts = repo_path / "handler.ts"
    handler_ts.write_text(
        "import { formatData } from './utils';\n\n"
        "export function processEvent(): string {\n"
        "    return formatData();\n"
        "}\n",
        encoding="utf-8",
    )


def _create_orchestrator() -> Phase1AnalysisOrchestrator:
    return Phase1AnalysisOrchestrator(
        analysis_service=MagicMock(),
        parser_service=MagicMock(),
        graph_service=MagicMock(),
        graph_store=MagicMock(),
        testing_service=MagicMock(),
        confidence_service=MagicMock(),
    )


def test_multilang_cpg_nodes_extracted_and_slices_computed(tmp_path: Path) -> None:
    _create_test_repository(tmp_path)
    orchestrator = _create_orchestrator()

    changed_paths = ("db.py", "utils.ts")
    orchestrator._run_semantic_cpg_poc(tmp_path, changed_paths, diff_text=None)

    cpg = orchestrator._last_cpg
    assert cpg is not None

    # Verify Python nodes were extracted
    assert "db.py:query" in cpg.nodes
    assert "service.py:handle_request" in cpg.nodes

    # Verify TypeScript nodes were extracted
    assert "utils.ts:formatData" in cpg.nodes
    assert "handler.ts:processEvent" in cpg.nodes

    slicer = GraphSlicer(cpg)

    # Verify Python slice: callers of db.py:query should include service.py:handle_request
    py_callers = slicer.extract_caller_slice("db.py:query")
    assert len(py_callers) == 1
    assert py_callers[0].symbol.id == "service.py:handle_request"
    assert py_callers[0].symbol.name == "handle_request"

    # Verify TypeScript slice: callers of utils.ts:formatData should include handler.ts:processEvent
    ts_callers = slicer.extract_caller_slice("utils.ts:formatData")
    assert len(ts_callers) == 1
    assert ts_callers[0].symbol.id == "handler.ts:processEvent"
    assert ts_callers[0].symbol.name == "processEvent"


def test_multilang_cpg_prunes_benign_callers_with_ai(
    tmp_path: Path, monkeypatch
) -> None:
    _create_test_repository(tmp_path)
    orchestrator = _create_orchestrator()

    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")

    with patch(
        "radius_analysis.ai.pruner.SemanticPruner.evaluate_impact", return_value=False
    ):
        changed_paths = ("db.py", "utils.ts")
        pruned_files = orchestrator._run_semantic_cpg_poc(
            tmp_path, changed_paths, diff_text="sample diff"
        )

    # Both Python and TypeScript dependent files should be pruned when evaluate_impact returns False
    assert "service.py" in pruned_files
    assert "handler.ts" in pruned_files


def test_diff_hunk_precision_only_slices_modified_symbol(
    tmp_path: Path, monkeypatch
) -> None:
    source_py = tmp_path / "source.py"
    source_py.write_text(
        "def foo():\n" "    return 'foo'\n\n" "def bar():\n" "    return 'bar'\n",
        encoding="utf-8",
    )

    caller_foo_py = tmp_path / "caller_foo.py"
    caller_foo_py.write_text(
        "from source import foo\n\n" "def use_foo():\n" "    return foo()\n",
        encoding="utf-8",
    )

    caller_bar_py = tmp_path / "caller_bar.py"
    caller_bar_py.write_text(
        "from source import bar\n\n" "def use_bar():\n" "    return bar()\n",
        encoding="utf-8",
    )

    orchestrator = _create_orchestrator()

    # diff modifies only line 2 (inside foo)
    diff_text = (
        "diff --git a/source.py b/source.py\n"
        "--- a/source.py\n"
        "+++ b/source.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def foo():\n"
        "-    return 'foo'\n"
        "+    return 'foo_updated'\n"
        " \n"
    )

    sliced_target_ids: list[str] = []
    original_extract = GraphSlicer.extract_caller_slice

    def spy_extract_caller_slice(self, target_node_id: str):
        sliced_target_ids.append(target_node_id)
        return original_extract(self, target_node_id)

    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    with patch(
        "radius_analysis.ai.pruner.SemanticPruner.evaluate_impact", return_value=False
    ):
        with patch.object(
            GraphSlicer,
            "extract_caller_slice",
            side_effect=spy_extract_caller_slice,
            autospec=True,
        ):
            pruned_files = orchestrator._run_semantic_cpg_poc(
                tmp_path, ("source.py",), diff_text=diff_text
            )

    # Only foo was modified in diff_text, so only foo's callers are sliced
    assert "source.py:foo" in sliced_target_ids
    assert "source.py:bar" not in sliced_target_ids

    # caller_foo.py was sliced and pruned, while caller_bar.py was untouched
    assert "caller_foo.py" in pruned_files
    assert "caller_bar.py" not in pruned_files
