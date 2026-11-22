"""Logowanie hasłem (GAME_PASSWORD)."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "game_password", "sekret123")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(auth.asyncio, "sleep", no_sleep)
    return TestClient(app)


def test_without_password_everything_is_open():
    settings.game_password = ""
    c = TestClient(app)
    assert c.get("/api/config").status_code == 200
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"


def test_blocks_api_and_pages_before_login(client):
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/health").status_code == 401
    for path in ["/", "/app.js", "/login.html"]:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    r = client.get("/login")
    assert r.status_code == 200 and 'name="password"' in r.text and "{{error}}" not in r.text


def test_wrong_password(client):
    r = client.post("/login", data={"password": "zle"}, follow_redirects=False)
    assert r.status_code == 401 and "Złe hasło" in r.text
    assert auth.COOKIE not in client.cookies
    assert client.get("/api/config").status_code == 401


def test_login_and_logout(client):
    r = client.post("/login", data={"password": "sekret123"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/config").status_code == 200
    assert client.get("/").status_code == 200

    client.get("/logout")
    assert client.get("/api/config").status_code == 401


def test_password_change_invalidates_session(client, monkeypatch):
    client.post("/login", data={"password": "sekret123"})
    assert client.get("/api/config").status_code == 200
    monkeypatch.setattr(settings, "game_password", "inne-haslo")
    assert client.get("/api/config").status_code == 401
