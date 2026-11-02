"""LK-03: the dynamic coverage-context linker flag is off by default."""

from __future__ import annotations

from radius_worker.config import WorkerSettings


def test_alias_and_default_off() -> None:
    field = WorkerSettings.model_fields["coverage_contexts_enabled"]
    assert field.alias == "RADIUS_FEATURE_COVERAGE_CONTEXTS"
    assert field.default is False


def test_flag_can_be_enabled_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_FEATURE_COVERAGE_CONTEXTS", "true")
    assert WorkerSettings().coverage_contexts_enabled is True
    monkeypatch.delenv("RADIUS_FEATURE_COVERAGE_CONTEXTS")
    assert WorkerSettings().coverage_contexts_enabled is False
