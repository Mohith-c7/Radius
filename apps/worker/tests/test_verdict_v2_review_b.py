"""Regression tests for code review B (B-02, B-03 and other worker-side findings)."""

from __future__ import annotations

import pytest
from radius_analysis.symbol_changes import (
    DictSnapshot,
    ExtractionOptions,
    extract_symbol_changes,
)
from radius_analysis.symbol_changes.testing import make_diff
from radius_analysis.tamper import TamperConfig, analyze_tampering
from radius_confidence.verdict_v2.domain.rules import is_blocking_degraded
from radius_worker.verdict_v2 import adapters

PY_BASE = {"src/a.py": "def f(x):\n    return x\n"}
PY_HEAD = {"src/a.py": "def f(x):\n    return x + 1\n"}


def _changeset(base: dict[str, str], head: dict[str, str]):
    diff = make_diff(base, head)
    return extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff, ExtractionOptions()), diff


def _markers(base, head):
    changeset, _ = _changeset(base, head)
    symbols = adapters.symbol_inputs(changeset).items
    return adapters.unanalyzed_file_markers(changeset, symbols)


# ------------------------------------------------------------------ B-02


@pytest.mark.parametrize(
    "path",
    ["deploy.sh", "Dockerfile", "main.go", "migrations/001.sql", "k8s/app.yml", "infra/main.tf"],
)
def test_b02_unknown_language_files_next_to_a_python_change_block(path: str) -> None:
    base = {**PY_BASE, path: "old\n"}
    head = {**PY_HEAD, path: "new\n"}
    markers = _markers(base, head)
    assert any(m.startswith("unanalyzed_files:") for m in markers), markers
    assert all(is_blocking_degraded(m) for m in markers)
    # the existing marker documented for D11 is produced too (language known as unknown)
    assert any(m.startswith("unsupported_language:") for m in markers)


def test_b02_ignored_paths_leave_a_trace() -> None:
    markers = _markers({**PY_BASE, "vendor/lib.py": "a = 1\n"}, {**PY_HEAD, "vendor/lib.py": "a = 2\n"})
    assert "unanalyzed_files:1" in markers


@pytest.mark.parametrize("path", ["README.md", "docs/guide.md", "uv.lock", "LICENSE", "changelog.d/1.fixed.md"])
def test_b02_inert_files_do_not_block(path: str) -> None:
    assert _markers({**PY_BASE, path: "old\n"}, {**PY_HEAD, path: "new\n"}) == ()


def test_b02_pure_python_change_has_no_marker() -> None:
    assert _markers(PY_BASE, PY_HEAD) == ()


def test_b02_unparseable_python_file_blocks() -> None:
    markers = _markers(PY_BASE, {"src/a.py": "def f(:\n  pass\n"})
    assert markers == ("unanalyzed_files:1",)


# ------------------------------------------------------------------ B-03

TEST_BASE = "def test_a():\n    assert f(1) == 2\n    assert f(2) == 3\n"
TEST_HEAD = "def test_a():\n    assert f(1) == 2\n"


def _tamper(base: dict[str, str], head: dict[str, str], config: dict | None = None):
    changeset, diff = _changeset(base, head)
    return analyze_tampering(
        changeset, DictSnapshot(base), DictSnapshot(head),
        TamperConfig.from_dict(config) if config else None, diff_text=diff,
    )


def test_b03_normal_test_file_reports_the_removed_assertion_and_no_marker() -> None:
    report = _tamper({"tests/test_a.py": TEST_BASE}, {"tests/test_a.py": TEST_HEAD})
    assert any(f.rule_id == "T003" for f in report.findings)
    assert adapters.tamper_unanalyzed_markers(report) == ()


def test_b03_removed_assertion_in_an_oversized_test_file_is_not_silent() -> None:
    pad = "# pad\n" * 400
    config = {"params": {"max_file_bytes": 500}}
    report = _tamper(
        {"tests/test_a.py": pad + TEST_BASE}, {"tests/test_a.py": pad + TEST_HEAD}, config
    )
    assert report.findings == ()  # the engine really saw nothing ...
    markers = adapters.tamper_unanalyzed_markers(report)
    assert markers == ("tamper_unanalyzed:files=1",)  # ... and that is now a blocking marker
    assert is_blocking_degraded(markers[0])


def test_b03_unanalyzable_documentation_does_not_block() -> None:
    pad = "text " * 400
    report = _tamper(
        {"docs/a.md": pad}, {"docs/a.md": pad + "more"}, {"params": {"max_file_bytes": 500}}
    )
    assert adapters.tamper_unanalyzed_markers(report) == ()


@pytest.mark.parametrize(
    "note",
    [
        "context_error:RuntimeError",
        "context_time_budget_exceeded",
        "max_files_exceeded",
        "base_snapshot_unavailable",
        "rule_time_budget_exceeded",
    ],
)
def test_b03_incomplete_engine_notes_block(note: str) -> None:
    report = type("R", (), {"unanalyzable": (), "notes": (note,)})()
    markers = adapters.tamper_unanalyzed_markers(report)
    assert markers == (f"tamper_unanalyzed:{note.split(':')[0]}",)
    assert is_blocking_degraded(markers[0])


# ------------------------------------------------------------------ B-02 exemptions


@pytest.mark.parametrize(
    "path", ["requirements.txt", "pyproject.toml", ".github/workflows/ci.yml", "pytest.ini", "tox.ini"]
)
def test_b02_files_the_tamper_catalog_inspects_do_not_block_here(path: str) -> None:
    # CI, manifests and test configuration are analysed by the tamper layer (its failures
    # are B-03's markers); the other unknown files are not
    assert _markers({**PY_BASE, path: "a = 1\n"}, {**PY_HEAD, path: "a = 2\n"}) == ()


# ------------------------------------------------------------------ B-05 / B-06

import importlib.util  # noqa: E402
import sys  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402

from radius_evidence.domain.config import VerdictV2Config  # noqa: E402
from radius_evidence.domain.inputs import CriterionInput, CriterionSymbolEdgeInput  # noqa: E402
from radius_evidence.domain.model import Reason  # noqa: E402
from radius_worker.verdict_v2 import scoring  # noqa: E402

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "benchmarks" / "fixtures").is_dir())
_FIX = _ROOT / "benchmarks" / "fixtures" / "verdict_v2"


def _stage_b(name: str):
    sys.path.insert(0, str(_FIX))
    try:
        spec = importlib.util.spec_from_file_location("vv2_loader_review_b", _FIX / "loader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.stage_b(name, mode="gold", scenario="head")
    finally:
        sys.path.remove(str(_FIX))


def _score(stage_b):
    return scoring.ScoringPipeline(mode="shadow").score_full(stage_b).payload


def test_b05_author_weights_do_not_hide_unproven_criteria() -> None:
    sb = _stage_b("08_multi_criterion_partial_evidence")
    sa = sb.stage_a
    honest = _score(sb)
    # the author gives every unproven criterion a tiny weight, nobody trusted confirmed them
    proven = {c["criterion_id"] for c in honest["criteria"] if c["state"] == "proven"}
    gamed = tuple(
        replace(
            c,
            provenance="author_head_spec",
            hints_provenance="author_head_spec",
            weight=1.0 if c.criterion_id in proven else 0.01,
        )
        for c in sa.criteria
    )
    gamed_payload = _score(replace(sb, stage_a=replace(sa, criteria=gamed)))
    assert {c["weight"] for c in gamed_payload["criteria"]} == {1.0}  # ignored
    plain = _score(
        replace(
            sb,
            stage_a=replace(
                sa,
                criteria=tuple(
                    replace(c, provenance="author_head_spec", hints_provenance="author_head_spec", weight=1.0)
                    for c in sa.criteria
                ),
            ),
        )
    )
    assert gamed_payload["summary"]["uim"] == plain["summary"]["uim"]
    assert gamed_payload["verdict"] == plain["verdict"]


def test_b05_trusted_weights_are_kept() -> None:
    cs = (
        CriterionInput("a", "t", 0.4, "behavioral_testable", "confirmed", provenance="human_confirmed"),
        CriterionInput("b", "t", 0.4, "behavioral_testable", "confirmed", provenance="base_spec"),
        CriterionInput("c", "t", 0.4, "behavioral_testable", "proposed", provenance="author_head_spec"),
        CriterionInput("d", "t", 0.4, "behavioral_testable", "proposed", provenance="llm_proposed"),
    )
    assert [c.weight for c in scoring.effective_criteria(cs)] == [0.4, 0.4, 1.0, 1.0]


def _edge(cid: str, sid: str, score: float, linkers: dict[str, float], code: str) -> CriterionSymbolEdgeInput:
    return CriterionSymbolEdgeInput(cid, sid, score, 1, linkers, (Reason(code, "d", "explicit"),))


def _sa_with(edges, prov="author_head_spec"):
    sb = _stage_b("08_multi_criterion_partial_evidence")
    sa = sb.stage_a
    crit = replace(sa.criteria[0], provenance=prov, hints_provenance=prov)
    return replace(sa, criteria=(crit,), criterion_symbol=tuple(edges)), crit.criterion_id


def test_b06_hint_only_links_are_capped_and_glob_hints_do_not_count_for_coverage() -> None:
    cfg = VerdictV2Config()
    sa, cid = _sa_with(
        [
            _edge("X", "s_glob", 0.9, {"explicit": 0.9}, "path_hint"),
            _edge("X", "s_sym", 0.95, {"explicit": 0.95}, "path_symbol_hint"),
            _edge("X", "s_both", 0.9, {"explicit": 0.9, "lexical": 0.5}, "path_hint"),
        ]
    )
    sa = replace(sa, criterion_symbol=tuple(replace(e, criterion_id=cid) for e in sa.criterion_symbol))
    edges, hint_only, no_cover = scoring.apply_author_edge_cap(sa, cfg.link, cfg.link.author_hint_cap)
    by = {e.symbol_id: e for e in edges}
    limit = cfg.link.link_sat_cs * cfg.link.author_hint_cap
    assert by["s_glob"].score == pytest.approx(limit) and by["s_sym"].score == pytest.approx(limit)
    assert by["s_both"].score == 0.9  # an independent linker corroborates it
    assert hint_only == {(cid, "s_glob"), (cid, "s_sym")}
    assert no_cover == {(cid, "s_glob")}  # only a concrete symbol hint may cover


def test_b06_trusted_provenance_is_not_capped() -> None:
    cfg = VerdictV2Config()
    for prov in ("base_spec", "human_confirmed"):
        sa, cid = _sa_with([_edge("X", "s", 0.9, {"explicit": 0.9}, "path_hint")], prov)
        sa = replace(sa, criterion_symbol=(replace(sa.criterion_symbol[0], criterion_id=cid),))
        edges, hint_only, _ = scoring.apply_author_edge_cap(sa, cfg.link, cfg.link.author_hint_cap)
        assert edges[0].score == 0.9 and not hint_only


def test_b06_one_glob_hint_no_longer_covers_the_whole_change() -> None:
    sb = _stage_b("05_scope_creep")
    sa = sb.stage_a
    live = [c for c in sa.criteria]
    cid = live[0].criterion_id
    others = [s for s in sa.symbols if s.is_behavioral and not s.is_test and not s.is_pseudo]
    edges = tuple(
        CriterionSymbolEdgeInput(cid, s.symbol_id, 0.9, 1, {"explicit": 0.9}, (Reason("path_hint", "d", "explicit"),))
        for s in others
    )
    gamed = replace(
        sa,
        criteria=(replace(live[0], provenance="author_head_spec", hints_provenance="author_head_spec"),),
        criterion_symbol=edges,
    )
    payload = _score(replace(sb, stage_a=gamed))
    assert payload["summary"]["intent_coverage"] == 0.0
