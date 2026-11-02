"""API observability: request ids, /metrics, and readiness failures."""

import pytest
from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_shared.observability import metrics


@pytest.fixture(autouse=True)
def reset_metrics():
    yield
    metrics.configure_metrics(False)


def test_metrics_endpoint_is_off_by_default() -> None:
    client = TestClient(create_app())

    assert client.get("/metrics").status_code == 404


def test_metrics_endpoint_serves_prometheus_when_enabled(monkeypatch) -> None:
    pytest.importorskip("prometheus_client")
    monkeypatch.setenv("RADIUS_METRICS_ENABLED", "true")
    client = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "radius_queue_depth" in response.text


def test_request_id_is_generated_and_echoed() -> None:
    client = TestClient(create_app())

    generated = client.get("/api/v1/health").headers["X-Request-ID"]
    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    unsafe = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\t;"})

    assert len(generated) == 32
    assert echoed.headers["X-Request-ID"] == "abc-123"
    assert unsafe.headers["X-Request-ID"] != "bad id\t;"


def test_ready_returns_503_without_leaking_detail_when_sql_is_down() -> None:
    app = create_app()
    app.state.settings.storage_backend = "sql"
    app.state.container.session_factory = None
    client = TestClient(app)

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "not_ready"
    assert "SQL storage" not in response.text


def test_ready_checks_the_sql_queue_table(tmp_path, monkeypatch) -> None:
    from radius_shared.database.base import Base
    from sqlalchemy import create_engine

    url = f"sqlite+pysqlite:///{(tmp_path / 'ready.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    from radius_api.config import get_api_settings

    get_api_settings.cache_clear()
    client = TestClient(create_app())

    # Database reachable but the queue table is missing -> not ready.
    assert client.get("/api/v1/ready").status_code == 503

    Base.metadata.create_all(create_engine(url))
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
