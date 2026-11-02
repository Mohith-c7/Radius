"""Verdict v2 flag (VD-07-lite): off by default; the worker package imports cleanly."""

from __future__ import annotations

import importlib

import pytest
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_worker.config import WorkerSettings


def test_alias_and_default_off() -> None:
    field = WorkerSettings.model_fields["verdict_v2_mode"]
    assert field.alias == "RADIUS_FEATURE_VERDICT_V2"
    assert field.default is VerdictV2Mode.OFF


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, VerdictV2Mode.OFF),
        ("false", VerdictV2Mode.OFF),
        ("0", VerdictV2Mode.OFF),
        ("off", VerdictV2Mode.OFF),
        ("garbage", VerdictV2Mode.OFF),
        ("shadow", VerdictV2Mode.SHADOW),
        ("true", VerdictV2Mode.ON),
        ("1", VerdictV2Mode.ON),
        ("on", VerdictV2Mode.ON),
    ],
)
def test_environment_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.delenv("RADIUS_FEATURE_VERDICT_V2", raising=False)
    if raw is not None:
        monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", raw)
    assert WorkerSettings().verdict_v2_mode is expected


def test_v1_feature_flags_are_unaffected(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", "on")
    settings = WorkerSettings()
    assert settings.intent_ingestion_enabled is False
    assert settings.symbol_changes_enabled is False
    assert settings.coverage_contexts_enabled is False


@pytest.mark.parametrize(
    "module",
    [
        "ports",
        "collect",
        "adapters",
        "sources",
        "scoring",
        "store",
        "requests",
        "publish",
    ],
)
def test_verdict_v2_worker_modules_import(module: str) -> None:
    importlib.import_module(f"radius_worker.verdict_v2.{module}")


def test_runner_references_verdict_v2_only_through_the_publish_and_outbox_hooks() -> None:
    import radius_worker.runner as runner

    with open(runner.__file__, encoding="utf-8") as handle:
        source = handle.read()
    imported = {
        line.split()[1]
        for line in source.splitlines()
        if line.startswith("from radius_worker.verdict_v2")
    }
    # VS-07/VS-08 hooks only; the Stage A/B hook (VS-05) is a flag-guarded local import.
    assert imported <= {
        "radius_worker.verdict_v2.publish",
        "radius_worker.verdict_v2.requests",
    }
