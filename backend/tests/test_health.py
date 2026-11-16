import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ml.model_loader import ModelsNotTrainedError


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "check_db_connection", lambda: True)
    with TestClient(main.app) as c:
        yield c


def test_liveness_does_not_depend_on_db_or_models(monkeypatch):
    def broken():
        raise RuntimeError("down")

    monkeypatch.setattr(main, "check_db_connection", broken)
    monkeypatch.setattr(main, "get_models", broken)
    # No `with`: skips the lifespan startup, which would also hit the patched loaders.
    assert TestClient(main.app).get("/health/live").json() == {"status": "alive"}


def test_ready_when_database_and_models_are_available(client):
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_ready_is_503_when_models_are_not_trained(client, monkeypatch):
    def missing():
        raise ModelsNotTrainedError("no artifacts")

    monkeypatch.setattr(main, "get_models", missing)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert "no artifacts" in resp.json()["detail"]
    # The older endpoint keeps reporting 200 with a field, for existing callers.
    assert client.get("/health").json()["ml_models"] == "not_trained"


def test_ready_is_503_when_database_is_down(monkeypatch):
    def down():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(main, "check_db_connection", down)
    with TestClient(main.app) as c:
        resp = c.get("/health/ready")
    assert resp.status_code == 503
    assert "database unavailable" in resp.json()["detail"]
