"""pytest suite for the devops-health-check Flask app (uses app.test_client())."""

import pytest

from app import APP_VERSION, create_app


@pytest.fixture()
def client():
    return create_app().test_client()


# AC-1: /health is unconditional liveness
def test_health_returns_200_with_identity(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["service"] == "devops-health-check"
    assert body["version"] == APP_VERSION == "0.1.0"
    assert body["status"] == "healthy"
    assert body["timestamp"]  # ISO timestamp present


def test_health_ignores_app_ready(client, monkeypatch):
    # Liveness must pass even when the service is not ready.
    monkeypatch.setenv("APP_READY", "false")
    assert client.get("/health").status_code == 200


# AC-2: readiness default (env unset) and truthy values
def test_ready_defaults_to_true_when_unset(client, monkeypatch):
    monkeypatch.delenv("APP_READY", raising=False)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json() == {"ready": True}


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes"])
def test_ready_truthy_values(client, monkeypatch, value):
    monkeypatch.setenv("APP_READY", value)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json()["ready"] is True


# AC-3: readiness failure branch -> 503 with reason
@pytest.mark.parametrize("value", ["false", "False", "0", "no", "", "maybe"])
def test_ready_falsy_values_return_503_with_reason(client, monkeypatch, value):
    monkeypatch.setenv("APP_READY", value)
    resp = client.get("/ready")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["ready"] is False
    assert body["reason"] == "APP_READY is not enabled"


# AC-4: unknown path -> 404
def test_unknown_path_returns_404(client):
    resp = client.get("/nope")
    assert resp.status_code == 404


# AC-5: disallowed method on an existing route -> 405
def test_post_health_returns_405(client):
    assert client.post("/health").status_code == 405


def test_put_ready_returns_405(client):
    assert client.put("/ready").status_code == 405
