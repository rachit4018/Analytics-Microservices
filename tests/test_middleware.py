from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_request_id_generated():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert "X-Process-Time-Ms" in resp.headers


def test_request_id_propagated_from_gateway():
    resp = client.get("/health", headers={"X-Request-ID": "gw-abc-123"})
    assert resp.headers["X-Request-ID"] == "gw-abc-123"


def test_validation_error_is_structured():
    # Assumes POST /events exists with a Pydantic body
    resp = client.post("/events", json={"bad": "payload"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "request_id" in body


def test_metrics_endpoint_exposes_counters():
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text