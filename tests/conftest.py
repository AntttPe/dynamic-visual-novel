import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def no_game_password(monkeypatch):
    """Testy nie zależą od GAME_PASSWORD z lokalnego .env. Logowanie sprawdza tests/test_auth.py."""
    monkeypatch.setattr(settings, "game_password", "")
