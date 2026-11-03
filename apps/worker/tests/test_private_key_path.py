"""GITHUB_APP_PRIVATE_KEY_PATH is honoured by the worker settings."""

from radius_worker.config import WorkerSettings
from radius_worker.runner import _github_settings


def test_worker_reads_the_app_key_from_a_file(tmp_path, monkeypatch) -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nZmFrZQ==\n-----END PRIVATE KEY-----\n"
    path = tmp_path / "app.pem"
    path.write_text(pem, encoding="utf-8")
    monkeypatch.setenv("GITHUB_APP_ID", "77")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(path))

    settings = WorkerSettings()

    assert settings.github_app_private_key == pem
    assert _github_settings(settings).enabled
