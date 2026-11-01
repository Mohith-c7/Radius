"""Demo seeding must be opt-in and never run in production."""

from fastapi.testclient import TestClient
from radius_api import main as api_main
from radius_api.config import get_api_settings
from radius_api.seed import BOTTLE_ANALYSIS_ID, EMITTERY_ANALYSIS_ID


def _start_app(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_api_settings.cache_clear()
    calls: list[object] = []

    import radius_api.seed as seed_module

    original = seed_module.seed_open_source_results

    def recording_seed(container):
        calls.append(container)
        original(container)

    monkeypatch.setattr(seed_module, "seed_open_source_results", recording_seed)
    app = api_main.create_app()
    with TestClient(app):
        pass
    get_api_settings.cache_clear()
    return app, calls


def test_startup_does_not_seed_demo_data_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RADIUS_SEED_DEMO_DATA", raising=False)
    app, calls = _start_app(monkeypatch, RADIUS_ENV="development")

    assert calls == []
    store = app.state.container.analysis_store
    assert store.get_by_id(BOTTLE_ANALYSIS_ID) is None
    assert store.get_by_id(EMITTERY_ANALYSIS_ID) is None


def test_production_never_seeds_even_when_flag_is_set(monkeypatch) -> None:
    app, calls = _start_app(
        monkeypatch,
        RADIUS_ENV="production",
        RADIUS_SEED_DEMO_DATA="true",
        API_KEYS="00000000-0000-4000-8000-000000000001:test-key",
    )

    assert calls == []
    assert app.state.container.analysis_store.get_by_id(BOTTLE_ANALYSIS_ID) is None


def test_flag_enables_clearly_labelled_demo_fixtures(monkeypatch) -> None:
    app, calls = _start_app(
        monkeypatch,
        RADIUS_ENV="development",
        RADIUS_SEED_DEMO_DATA="true",
    )

    assert len(calls) == 1
    report = app.state.container.confidence_store.get_by_analysis_id(
        BOTTLE_ANALYSIS_ID
    )
    assert report is not None
    assert report.summary.startswith("DEMO FIXTURE (not a real analysis)")
    assert report.verification_status == "insufficient_evidence"
    assert not any("safe to merge" in item.lower() for item in report.recommendations)


def test_should_seed_demo_data_requires_flag_and_non_production() -> None:
    class _Settings:
        def __init__(self, flag, environment):
            self.seed_demo_data = flag
            self.environment = environment

    from radius_shared.config import RuntimeEnvironment

    assert not api_main.should_seed_demo_data(
        _Settings(False, RuntimeEnvironment.DEVELOPMENT)
    )
    assert not api_main.should_seed_demo_data(
        _Settings(True, RuntimeEnvironment.PRODUCTION)
    )
    assert api_main.should_seed_demo_data(_Settings(True, RuntimeEnvironment.DEVELOPMENT))
