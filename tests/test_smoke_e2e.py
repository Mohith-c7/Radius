"""Pytest wrapper for ``scripts/smoke_e2e.py`` (API + worker + PostgreSQL smoke).

The smoke itself needs a PostgreSQL server, so it is skipped unless
``RADIUS_SMOKE=1`` and ``DATABASE_URL`` points at PostgreSQL. It runs in a fresh
subprocess (clean environment, no import-time settings leaking between tests):

    docker compose up -d postgres
    RADIUS_SMOKE=1 DATABASE_URL=postgresql+psycopg://radius:radius@localhost:5432/radius \
        python -m pytest tests/test_smoke_e2e.py

The helper tests below always run (no database).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_e2e.py"


def _load():
    spec = importlib.util.spec_from_file_location("smoke_e2e", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load()
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_WANTED = os.environ.get("RADIUS_SMOKE") == "1" and DATABASE_URL.startswith("postgres")


@pytest.mark.skipif(not _WANTED, reason="set RADIUS_SMOKE=1 and a PostgreSQL DATABASE_URL to run the smoke")
def test_end_to_end_smoke() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + "\n" + result.stderr[-4000:]
    assert "SMOKE PASSED" in result.stdout


def test_script_requires_a_database_url() -> None:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stderr


def test_intent_spec_carries_the_fixture_gold_links() -> None:
    expected = json.loads((smoke.FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
    spec = smoke.intent_spec(expected)
    assert spec.startswith("version: 1\ncriteria:\n")
    for criterion in expected["criteria"]:
        assert f"- id: {criterion['id']}" in spec
    for link in expected["links"]:
        for test in link["tests"]:
            assert f'"{test}"' in spec


def test_junit_report_maps_test_ids_to_classnames() -> None:
    xml = smoke.junit_from_outcomes(
        {"tests/test_a.py::test_x": "passed", "tests/test_a.py::test_y": "failed"}
    ).decode()
    assert 'classname="tests.test_a" name="test_x"' in xml
    assert "<failure" in xml


def test_fake_github_rejects_unsigned_and_unknown_calls() -> None:
    fake = smoke.FakeGitHub(public_key_pem="", head_sha="a" * 40, spec="")
    status, _ = fake.handle("GET", "https://api.github.com/repos/o/r/pulls", {}, None)
    assert status == 401
    status, _ = fake.handle(
        "GET", "https://api.github.com/repos/smoke-org/x/unknown",
        {"Authorization": "Bearer ghs_x"}, None,
    )
    assert status == 404 and fake.unhandled


def test_fixture_selectors_resolve_to_one_directory() -> None:
    assert smoke.fixture_dir("03").name == "03_incorrect_passes_weak_tests"
    assert smoke.fixture_dir("08_multi").name == "08_multi_criterion_partial_evidence"
    assert [smoke.fixture_dir(n).name[:2] for n in smoke.DEFAULT_FIXTURES] == ["01", "04"]
    with pytest.raises(SystemExit):
        smoke.fixture_dir("99")


def test_known_deviations_are_real_and_explained() -> None:
    doc = json.loads(smoke.EXPECTATIONS.read_text(encoding="utf-8"))
    by_name = {f["fixture"]: f for f in doc["fixtures"]}
    for name, dev in smoke.KNOWN_E2E_DEVIATIONS.items():
        exp = by_name[name]
        for key in ("verdict", "decided_by"):
            if key in dev:
                want = exp["expected_verdict"] if key == "verdict" else exp["decided_by"].split(" ")[0]
                assert dev[key][0] != want and len(dev[key][1]) > 20, (name, key)
        for cid, (state, why) in dev.get("states", {}).items():
            assert state != exp["gold"]["states"][cid] and len(why) > 20, (name, cid)
        for cid, (value, why) in dev.get("S", {}).items():
            assert abs(value - exp["gold"]["S"][cid]) > doc["tolerance"] and len(why) > 20, (name, cid)
    offline = by_name["06_hallucinated_dependency"]["offline_registry_variant"]
    assert smoke.KNOWN_E2E_DEVIATIONS["06_hallucinated_dependency"]["verdict"][0] == offline["expected_verdict"]
