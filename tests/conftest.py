import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def no_accounts(monkeypatch):
    """Testy nie zależą od haseł i sekretu z lokalnego .env. Konta sprawdza tests/test_auth.py."""
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "game_password", "")
    monkeypatch.setattr(settings, "secret_key", "sekret-testow")
