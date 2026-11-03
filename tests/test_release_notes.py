"""Unit tests for scripts/release_notes.py (local files only)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("release_notes", _SCRIPT)
rn = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rn
_spec.loader.exec_module(rn)


def test_parse_tag() -> None:
    assert rn.parse_tag("v1.2.3") == "1.2.3"
    assert rn.parse_tag("v0.1.0-rc.1") == "0.1.0-rc.1"
    for bad in ("1.2.3", "v1.2", "vx", "release-1"):
        with pytest.raises(ValueError):
            rn.parse_tag(bad)


def test_notes_group_by_category_and_skip_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("ignore me", encoding="utf-8")
    (tmp_path / "b.fixed.md").write_text("Fixed   a thing.\n", encoding="utf-8")
    (tmp_path / "a.added.md").write_text("Added a thing.\n", encoding="utf-8")
    text = rn.render_notes(rn.collect_fragments(tmp_path), "1.0.0")
    assert text.startswith("## Radius 1.0.0")
    assert text.index("### Added") < text.index("### Fixed")
    assert "- Fixed a thing." in text
    assert "ignore me" not in text


def test_unknown_category_rejected(tmp_path: Path) -> None:
    (tmp_path / "x.bogus.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        rn.collect_fragments(tmp_path)


def test_empty_notes() -> None:
    assert "No changelog fragments" in rn.render_notes({})


def test_version_problems() -> None:
    versions = {"pyproject.toml": "0.1.0", "package.json": "0.1.0"}
    assert rn.version_problems(versions, "v0.1.0") == []
    assert rn.version_problems(versions, "v0.2.0") != []
    assert rn.version_problems({"pyproject.toml": "0.1.0", "x": "0.2.0"}) == ["x: 0.2.0 != 0.1.0"]


def test_declared_versions_reads_all_sources(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
    docker = tmp_path / "apps" / "api"
    docker.mkdir(parents=True)
    (docker / "Dockerfile").write_text("ARG RADIUS_VERSION=1.0.1\n", encoding="utf-8")
    versions = rn.declared_versions(tmp_path)
    assert versions == {"pyproject.toml": "1.0.0", "package.json": "1.0.0", "apps/api/Dockerfile": "1.0.1"}
    assert len(rn.version_problems(versions)) == 1


def test_repository_versions_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    assert rn.version_problems(rn.declared_versions(root)) == []
