"""The generated configuration reference must match the code (PRD-17)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_config_reference.py"
_spec = importlib.util.spec_from_file_location("gen_config_reference", _SCRIPT)
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)


def test_reference_file_is_up_to_date(capsys) -> None:
    rc = gen.main(["--check"])
    err = capsys.readouterr().err
    assert rc == 0, err


def test_every_env_variable_in_source_is_documented() -> None:
    entries, undocumented = gen.collect()
    assert undocumented == []
    assert all(e.description for e in entries)


def test_known_variables_and_defaults() -> None:
    entries = {e.name: e for e in gen.collect()[0]}
    assert entries["WORKER_FLAKY_POLICY"].default == "exclude"
    assert entries["WORKER_TEST_RERUNS"].default == "0"
    assert entries["WORKER_TEST_EXECUTION_MODE"].default == "unset"
    assert entries["RADIUS_FEATURE_VERDICT_V2"].default == "off"
    assert entries["RADIUS_FEATURE_GEMINI_PRUNER"].default == "false"


def test_secrets_are_flagged() -> None:
    entries = {e.name: e for e in gen.collect()[0]}
    for name in ("API_KEYS", "GITHUB_WEBHOOK_SECRET", "GITHUB_APP_PRIVATE_KEY", "ANTHROPIC_API_KEY",
                 "GEMINI_API_KEY", "SESSION_SECRET", "SMTP_PASSWORD", "DATABASE_URL", "RADIUS_API_KEY"):
        assert entries[name].secret, name
    assert not entries["WORKER_POLL_INTERVAL_SECONDS"].secret
    assert not entries["RADIUS_LLM_INTENT_ORG_TOKEN_CAP"].secret


def test_check_detects_drift(tmp_path, monkeypatch) -> None:
    stale = tmp_path / "CONFIGURATION.md"
    stale.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(gen, "OUTPUT", stale)
    assert gen.main(["--check"]) == 1
