"""EV-02: catalog completeness, F-14 fixture sanity, classification parity, eval script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from radius_analysis.tamper import (
    CATALOG_VERSION,
    TamperConfig,
    catalog_markdown,
    default_registry,
)
from radius_analysis.tamper.__main__ import main as tamper_cli
from radius_analysis.tamper.classify import Role, classify_path, is_test_path

sys.path.insert(0, str(Path(__file__).parent))
from tamper_support import load_cases  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
DOC_PAGE = ROOT / "docs" / "evidence" / "TAMPER_RULES.md"
README = ROOT / "packages" / "analysis" / "src" / "radius_analysis" / "tamper" / "README.md"
REGISTRY = default_registry()
CASES = load_cases()


def _load_eval():
    spec = importlib.util.spec_from_file_location("tamper_eval", ROOT / "scripts" / "tamper_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tamper_eval"] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ completeness


@pytest.mark.parametrize("rule", REGISTRY.all(), ids=lambda r: r.id)
def test_every_rule_is_documented(rule) -> None:  # noqa: ANN001
    doc = rule.doc
    for field in ("title", "rationale", "example_before", "example_after", "limitations", "maps_to"):
        assert getattr(doc, field).strip(), f"{rule.id}.doc.{field} is empty"
    assert rule.checks and all(c.description.strip() for c in rule.checks.values())
    page = DOC_PAGE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    assert f"### {rule.id}" in page, f"{rule.id} missing from TAMPER_RULES.md"
    assert rule.doc.title in page
    assert rule.id in readme, f"{rule.id} missing from the tamper README"
    for check in rule.checks:
        assert f"`{check}`" in page, f"check {rule.id}:{check} not documented"


@pytest.mark.parametrize("rule", REGISTRY.all(), ids=lambda r: r.id)
def test_every_rule_has_positive_and_negative_fixtures(rule) -> None:  # noqa: ANN001
    mine = [c for c in CASES if c["rule"] == rule.id]
    positives = [c for c in mine if any(e.startswith(f"{rule.id}:") for e in c["expect"])]
    negatives = [c for c in mine if not any(e.startswith(f"{rule.id}:") for e in c["expect"])]
    assert positives, f"{rule.id} has no positive case"
    assert negatives, f"{rule.id} has no negative / near-miss case"


def test_every_check_has_a_positive_case() -> None:
    covered = {e for c in CASES for e in c["expect"]}
    missing = [
        f"{r.id}:{check}" for r in REGISTRY.all() for check in r.checks
        if f"{r.id}:{check}" not in covered
    ]
    assert not missing, f"checks without a positive case: {missing}"


def test_catalog_table_in_docs_is_in_sync() -> None:
    page = DOC_PAGE.read_text(encoding="utf-8")
    assert catalog_markdown(REGISTRY) in page, (
        "regenerate the table: python -m radius_analysis.tamper catalog-md"
    )
    assert CATALOG_VERSION in page


def test_design_ids_t001_to_t016_are_all_implemented() -> None:
    ids = REGISTRY.ids()
    assert {f"T{n:03d}" for n in range(1, 17)} <= ids
    assert "T017" in ids


def test_default_severities_are_declared_as_assumed_in_the_docs() -> None:
    assert "assumed_severity" in README.read_text(encoding="utf-8")


# ------------------------------------------------------------------ F-14 sanity


@pytest.mark.parametrize("fixture", sorted(p.name for p in FIXTURES.iterdir() if (p / "base").is_dir()))
def test_f14_fixture_matches_expected_json(fixture: str) -> None:
    result = _load_eval().evaluate_fixture(FIXTURES / fixture, TamperConfig())
    assert result["missing"] == [], result
    assert result["unexpected"] == [], result
    assert result["rule_errors"] == []
    assert result["unanalyzable"] == []


def test_f14_fixture_04_and_06_have_the_documented_rules() -> None:
    mod = _load_eval()
    r04 = mod.evaluate_fixture(FIXTURES / "04_test_tampering", TamperConfig())
    assert sorted(f["rule"] for f in r04["findings"]) == ["T001", "T002", "T004", "T005"]
    assert {f["severity"] for f in r04["findings"]} == {"high"}
    r06 = mod.evaluate_fixture(FIXTURES / "06_hallucinated_dependency", TamperConfig())
    assert [(f["rule"], f["file"]) for f in r06["findings"]] == [("T012", "requirements.txt")]
    for clean in ("01_correct_strong_tests", "02_correct_weak_tests"):
        assert mod.evaluate_fixture(FIXTURES / clean, TamperConfig())["findings"] == []


def test_eval_script_cli(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_eval()
    assert mod.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "not a research result" in out and "T012: 1" in out
    assert mod.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["per_rule_hits"]["T004"] == 1 and len(data["fixtures"]) == 8


def test_eval_script_check_fails_on_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import shutil

    target = tmp_path / "04_test_tampering"
    shutil.copytree(FIXTURES / "04_test_tampering", target)
    expected = json.loads((target / "expected.json").read_text(encoding="utf-8"))
    expected["tamper_findings"].append({"rule": "T009", "file": "pytest.ini", "assumed_severity": "high"})
    (target / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
    mod = _load_eval()
    assert mod.main([str(tmp_path), "--check"]) == 1
    assert "MISSING" in capsys.readouterr().out
    cfg = tmp_path / "off.json"
    cfg.write_text(json.dumps({"disable": ["T002"]}), encoding="utf-8")
    assert mod.main([str(tmp_path), "--config", str(cfg), "--check"]) == 1
    assert "MISSING    T002" in capsys.readouterr().out


# ------------------------------------------------------------------ CLI & classify


def test_cli_rules_and_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    assert tamper_cli(["rules"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in data] == sorted(r["id"] for r in data) and len(data) == 17
    assert tamper_cli(["catalog-md"]) == 0
    assert capsys.readouterr().out == catalog_markdown()


def test_cli_analyze(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fx = FIXTURES / "04_test_tampering"
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"disable": ["T001"]}), encoding="utf-8")
    assert tamper_cli(["analyze", str(fx / "base"), str(fx / "head"), str(fx / "pr.patch"),
                       "--config", str(cfg)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert sorted(f["rule_id"] for f in report["findings"]) == ["T002", "T004", "T005"]


PATH_TABLE = [
    "tests/test_a.py", "test_a.py", "src/a_test.py", "src/a.test.ts", "src/a.spec.tsx",
    "tests/helpers.py", "tests/fixtures/data.py", "tests/conftest.py", "tests/__init__.py",
    "tests/sub/util.py", "tests/_private.py", "src/a.py", "__tests__/x.js", "tests/data.json",
    "docs/tests/readme.md", "setup.py", "conftest.py", "pkg/tests/test_b.py", "test/x.py",
    "tests/__mocks__/m.py", "tests/data/x.py", "a/b/c_test.py",
]


@pytest.mark.parametrize("path", PATH_TABLE)
def test_test_path_convention_matches_testing_domain(path: str) -> None:
    pytest.importorskip("radius_testing")
    from radius_testing.infrastructure.discovery import ConventionalTestDiscoverer

    assert is_test_path(path) == ConventionalTestDiscoverer._is_test_path(path)


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("tests/test_a.py", Role.TEST), ("tests/conftest.py", Role.CONFTEST),
        (".github/workflows/ci.yml", Role.CI_WORKFLOW), ("Makefile", Role.BUILD_CONFIG),
        ("pyproject.toml", Role.MANIFEST), ("pyproject.toml", Role.BUILD_CONFIG),
        ("requirements-dev.txt", Role.MANIFEST), ("uv.lock", Role.LOCKFILE),
        ("tests/__snapshots__/a.snap", Role.SNAPSHOT), ("src/a.py", Role.SOURCE),
        ("README.md", Role.DOC), ("data.bin", Role.OTHER),
    ],
)
def test_classify_path(path: str, role: Role) -> None:
    assert role in classify_path(path)
