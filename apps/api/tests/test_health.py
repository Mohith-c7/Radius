from fastapi.testclient import TestClient
from radius_api.main import create_app


def test_health_endpoint_returns_service_metadata() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "status": "ok",
            "service": "radius-api",
            "environment": "development",
        },
        "error": None,
        "meta": {},
    }


def test_api_allows_dashboard_cors_preflight() -> None:
    client = TestClient(create_app())

    response = client.options(
        "/api/v1/repositories",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Radius-Organization-Id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
