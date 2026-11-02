"""The compose files and .env.example must pass scripts/check_compose.py."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_compose.py"
_spec = importlib.util.spec_from_file_location("check_compose", _SCRIPT)
checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = checker
_spec.loader.exec_module(checker)


def test_repository_files_pass() -> None:
    assert checker.run() == []


def test_session_secret_is_required_in_production_file() -> None:
    api_env = checker.load_yaml(checker.BASE)["services"]["api"]["environment"]
    assert api_env["SESSION_SECRET"].startswith("${SESSION_SECRET:?")
    assert api_env["RADIUS_ENV"] == "production"


def test_dev_override_is_development_and_uses_variables() -> None:
    dev = checker.load_yaml(checker.DEV)
    env = checker.environment_of(dev["services"]["api"])
    assert env["RADIUS_ENV"] == "development"
    assert env["EMAIL_DELIVERY_MODE"] == "log"
    assert "${RADIUS_API_KEY:?" in env["API_KEYS"]


def test_checker_flags_literal_default_secret() -> None:
    base = copy.deepcopy(checker.load_yaml(checker.BASE))
    base["services"]["api"]["environment"]["SESSION_SECRET"] = "${SESSION_SECRET:-abc}"
    assert any(p.startswith("R3") for p in checker.check_base(base))


def test_checker_flags_dev_switch_in_production_file() -> None:
    base = copy.deepcopy(checker.load_yaml(checker.BASE))
    base["services"]["api"]["environment"]["EMAIL_DELIVERY_MODE"] = "log"
    base["services"]["api"]["environment"]["RADIUS_ENV"] = "development"
    problems = checker.check_base(base)
    assert sum(p.startswith("R4") for p in problems) == 2


def test_checker_flags_open_postgres_port_and_duplicate_ports() -> None:
    base = copy.deepcopy(checker.load_yaml(checker.BASE))
    base["services"]["postgres"]["ports"] = ["5432:5432"]
    base["services"]["dashboard"]["ports"] = ["8000:3000"]
    problems = checker.check_base(base)
    assert any("postgres must be published on 127.0.0.1" in p for p in problems)
    assert any("host port 8000" in p for p in problems)


def test_checker_flags_missing_healthcheck() -> None:
    base = copy.deepcopy(checker.load_yaml(checker.BASE))
    del base["services"]["api"]["healthcheck"]
    problems = checker.check_base(base)
    assert any("api needs a healthcheck" in p for p in problems)
    assert any("waits for api" in p for p in problems)


def test_checker_flags_undocumented_variable() -> None:
    doc = {"services": {"api": {"environment": {"X": "${NOT_DOCUMENTED_ANYWHERE}"}}}}
    assert checker.check_var_refs("base", doc, {"OTHER"})
    ok = {"services": {"api": {"environment": {"X": "${NOT_DOCUMENTED_ANYWHERE:-1}"}}}}
    assert checker.check_var_refs("base", ok, {"OTHER"}) == []


def test_checker_flags_literal_secret_in_dev_override_and_env_example() -> None:
    dev = copy.deepcopy(checker.load_yaml(checker.DEV))
    base = checker.load_yaml(checker.BASE)
    dev["services"]["dashboard"]["environment"]["RADIUS_API_KEY"] = "literal"
    assert any(p.startswith("R7") for p in checker.check_dev(dev, base))
    assert checker.check_env_example({"SESSION_SECRET": "x" * 40})
    assert checker.check_env_example({"SESSION_SECRET": "your_secure_random_session_secret_min_32_chars"}) == []


def test_generated_dev_env_has_random_distinct_secrets(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_dev_env", Path(__file__).resolve().parents[1] / "scripts" / "gen_dev_env.py"
    )
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    first = gen.render(example)
    second = gen.render(example)
    values = {}
    for text in (first, second):
        values[text] = dict(
            line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
        )
    a, b = values[first], values[second]
    assert a["SESSION_SECRET"] != b["SESSION_SECRET"] and len(a["SESSION_SECRET"]) >= 32
    assert a["RADIUS_API_KEY"] != b["RADIUS_API_KEY"]
    assert a["RADIUS_API_KEY"].startswith("dev_")
    assert a["EMAIL_DELIVERY_MODE"] == "log" and a["DEV_AUTO_VERIFY_EMAIL"] == "true"
    assert a["GITHUB_DEFAULT_ORGANIZATION_ID"] == a["NEXT_PUBLIC_RADIUS_ORGANIZATION_ID"]
    target = tmp_path / ".env"
    assert gen.main(["--env-file", str(target)]) == 0
    before = target.read_text(encoding="utf-8")
    assert gen.main(["--env-file", str(target)]) == 0  # never overwrites
    assert target.read_text(encoding="utf-8") == before
