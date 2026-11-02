from radius_shared.config import LogLevel, RadiusBaseSettings, RuntimeEnvironment


def test_base_settings_defaults_to_development() -> None:
    settings = RadiusBaseSettings()

    assert settings.environment is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO


def test_base_settings_accepts_uat_environment() -> None:
    settings = RadiusBaseSettings(RADIUS_ENV="uat", RADIUS_LOG_LEVEL="ERROR")

    assert settings.environment is RuntimeEnvironment.UAT
    assert settings.log_level is LogLevel.ERROR


def test_blank_environment_values_are_treated_as_unset(monkeypatch) -> None:
    # .env.example ships blank values (e.g. GITHUB_DEFAULT_ORGANIZATION_ID=).
    monkeypatch.setenv("RADIUS_LOG_LEVEL", "")

    assert RadiusBaseSettings(_env_file=None).log_level is LogLevel.INFO
