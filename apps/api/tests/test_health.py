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
