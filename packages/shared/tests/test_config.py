from radius_shared.config import LogLevel, RadiusBaseSettings, RuntimeEnvironment


def test_base_settings_defaults_to_development() -> None:
    settings = RadiusBaseSettings()

    assert settings.environment is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO


def test_base_settings_accepts_uat_environment() -> None:
    settings = RadiusBaseSettings(RADIUS_ENV="uat", RADIUS_LOG_LEVEL="ERROR")

    assert settings.environment is RuntimeEnvironment.UAT
    assert settings.log_level is LogLevel.ERROR
