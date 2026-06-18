import os
import sys
import pytest


# Must be set BEFORE importing main — auth middleware reads API_KEY at import time
@pytest.fixture
def client_with_auth():
    """Client with API_KEY=secret — all protected endpoints require auth."""
    os.environ["API_KEY"] = "secret"
    # Force reimport so middleware picks up the env var
    for k in list(sys.modules.keys()):
        if k.startswith("main") or k.startswith("middleware"):
            del sys.modules[k]
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def client_no_auth():
    """Client with API_KEY='' — auth is disabled."""
    os.environ["API_KEY"] = ""
    for k in list(sys.modules.keys()):
        if k.startswith("main") or k.startswith("middleware"):
            del sys.modules[k]
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestAuthWithKey:
    def test_health_bypasses_auth(self, client_with_auth):
        resp = client_with_auth.get("/api/v1/health")
        assert resp.status_code == 200

    def test_docs_bypasses_auth(self, client_with_auth):
        resp = client_with_auth.get("/docs")
        assert resp.status_code == 200

    def test_api_rejects_without_key(self, client_with_auth):
        resp = client_with_auth.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_api_accepts_valid_key(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-API-Key": "secret"},
        )
        assert resp.status_code != 401

    def test_api_rejects_invalid_key(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401


class TestAuthDisabled:
    def test_no_key_required_when_empty(self, client_no_auth):
        resp = client_no_auth.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code != 401
