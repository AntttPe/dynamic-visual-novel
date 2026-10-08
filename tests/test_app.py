"""Test sprawdzający, czy środowisko działa.

Uruchomienie:  docker compose exec app pytest -v
"""

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ui_is_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dynamic Visual Novel" in resp.text


def test_chat_without_ollama_returns_clear_error(monkeypatch):
    monkeypatch.setattr(llm.settings, "ollama_base_url", "http://127.0.0.1:1")
    resp = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hej"}]})
    assert resp.status_code == 502


@pytest.mark.anyio
async def test_ollama_answers():
    """Opcjonalny: przechodzi tylko, gdy Ollama działa i model jest pobrany."""
    if not await llm.ollama_available():
        pytest.skip("Ollama nie działa, pomijam (to nie jest błąd)")
    reply = await llm.ollama_chat([{"role": "user", "content": "Odpowiedz jednym słowem: tak"}])
    assert reply.strip()
