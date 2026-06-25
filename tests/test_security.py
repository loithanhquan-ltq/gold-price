"""Test that protected endpoints reject requests without a valid API token."""
import os
os.environ.setdefault("API_TOKEN", "test-token-abc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_security.db")
os.environ.setdefault("GMAIL_USER", "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "dummy")
os.environ.setdefault("RECIPIENT_EMAIL", "test@example.com")

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_refresh_no_token_returns_401():
    res = client.post("/api/refresh")
    assert res.status_code == 401


def test_refresh_wrong_token_returns_401():
    res = client.post("/api/refresh", headers={"X-API-Token": "wrong"})
    assert res.status_code == 401


def test_email_test_no_token_returns_401():
    res = client.post("/api/email/test")
    assert res.status_code == 401


def test_health_is_public():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_history_is_public():
    # Use context manager so the lifespan (init_db) runs
    with TestClient(app) as c:
        res = c.get("/api/prices/history?days=1")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
