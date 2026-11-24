"""Konta: administrator z .env, gracze z bazy i ich przygotowane gry. Bez modelu: odpowiedzi daje FakeLLM."""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app import accounts, admin, auth
from app.config import settings
from app.images import BackgroundImages
from app.llm import LLMError
from app.llm.fake import FakeLLM
from app.main import GAMES, app
from app.storage.db import Store
from tests.test_app import narrator_json
from tests.test_world_builder import world_json

ADMIN = {"login": "administrator", "password": "sekret123"}
PLAYER = {"login": "ania", "password": "haslo-ani", "world_id": "custom", "world_idea": "Zwykłe osiedle, zgubiony pies.",
          "max_turns": 6, "difficulty": "easy", "model": "openai/strata-big",
          "text_api_base": "http://llm.example/v1", "text_api_key": "sk-tajny-klucz", "image_kind": "off"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_login", "administrator")
    monkeypatch.setattr(settings, "admin_password", "sekret123")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(auth.asyncio, "sleep", no_sleep)
    fake = FakeLLM()
    fake.apis = []

    def factory(model, world, **api):
        fake.apis.append((model, api))
        return fake

    old = app.state.llm_factory, app.state.store, app.state.images
    app.state.llm_factory = factory
    app.state.store = Store(tmp_path / "test.sqlite")
    app.state.images = BackgroundImages(None, tmp_path / "images")
    with TestClient(app) as client:
        yield client, fake
    app.state.llm_factory, app.state.store, app.state.images = old


def login(client, login, password):
    return client.post("/login", data={"login": login, "password": password}, follow_redirects=False)


def wait_ready(client, login_name):
    for _ in range(200):
        user = next(u for u in client.get("/api/admin/users").json() if u["login"] == login_name)
        if user["status"] != "pending":
            return user
        time.sleep(0.02)
    raise AssertionError("gra gracza nie przygotowała się")


def add_player(client, fake, **changes):
    fake.responses.append(world_json())
    resp = client.post("/api/admin/users", json={**PLAYER, **changes})
    assert resp.status_code == 201, resp.text
    return wait_ready(client, resp.json()["login"])


def test_without_password_everything_is_open():
    settings.admin_password = settings.game_password = ""
    c = TestClient(app)
    assert c.get("/api/config").status_code == 200
    assert c.get("/api/me").json() == {"login": "local", "role": "admin", "accounts": False}
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"


def test_blocks_api_and_pages_before_login(env):
    client, _ = env
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/admin/users").status_code == 401
    for path in ["/", "/app.js", "/admin"]:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    r = client.get("/login")
    assert r.status_code == 200 and 'name="login"' in r.text and 'name="password"' in r.text
    assert "{{" not in r.text


def test_wrong_password(env):
    client, _ = env
    r = login(client, "administrator", "zle")
    assert r.status_code == 401 and "Zły login albo hasło" in r.text and 'value="administrator"' in r.text
    assert auth.COOKIE not in client.cookies
    assert login(client, "nikt", "sekret123").status_code == 401


def test_admin_login_and_logout(env):
    client, _ = env
    r = login(client, **ADMIN)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/me").json() == {"login": "administrator", "role": "admin", "accounts": True}
    assert client.get("/admin").status_code == 200
    client.get("/logout")
    assert client.get("/api/config").status_code == 401


def test_old_game_password_still_logs_in_admin(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "game_password", "stare-haslo")
    assert login(client, "administrator", "stare-haslo").status_code == 303
    assert client.get("/api/me").json()["role"] == "admin"


def test_admin_password_change_logs_admin_out(env, monkeypatch):
    client, _ = env
    login(client, **ADMIN)
    monkeypatch.setattr(settings, "admin_password", "inne-haslo")
    assert client.get("/api/config").status_code == 401


def test_admin_prepares_game_and_player_plays_only_it(env):
    client, fake = env
    login(client, **ADMIN)
    other = client.post("/api/games", json={"world_id": "zaginiona_korona", "model": "fake/x"}).json()["game_id"]
    user = add_player(client, fake)
    assert user["status"] == "ready" and user["game_id"] and user["has_text_key"]
    assert "text_api_key" not in user["setup"] and "sk-tajny-klucz" not in str(user)
    # świat zbudował model z ustawień konta, z jego adresem i kluczem
    assert fake.apis[-1] == ("openai/strata-big", {"api_base": "http://llm.example/v1", "api_key": "sk-tajny-klucz"})
    client.get("/logout")

    assert login(client, "ania", "haslo-ani").status_code == 303
    me = client.get("/api/me").json()
    assert me["role"] == "player" and me["status"] == "ready" and me["game_id"] == user["game_id"]
    game = client.get(f"/api/games/{me['game_id']}").json()
    assert game["world"]["title"] == "Zaginiony android" and game["max_turns"] == 6 and game["difficulty"] == "easy"
    assert game["image_model"] is None  # grafika wyłączona w ustawieniach konta
    fake.responses.append(narrator_json())
    assert client.post(f"/api/games/{me['game_id']}/turns", json={"action": "Rozglądam się"}).status_code == 200
    assert [g["game_id"] for g in client.get("/api/games").json()] == [me["game_id"]]
    # cudza gra, nowa gra i panel administratora są zablokowane
    assert client.get(f"/api/games/{other}").status_code == 404
    assert client.get(f"/api/games/{other}/comic").status_code == 404
    assert client.post("/api/games", json={"world_id": "zaginiona_korona"}).status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/"


def test_api_keys_are_encrypted_in_database(env):
    client, fake = env
    login(client, **ADMIN)
    add_player(client, fake)
    with sqlite3.connect(app.state.store.path) as conn:
        dump = "\n".join(conn.iterdump())
    assert "sk-tajny-klucz" not in dump and "haslo-ani" not in dump
    secrets = app.state.store.user("ania")["secrets"]
    assert accounts.decrypt(secrets) == {"text_api_key": "sk-tajny-klucz"}


def test_player_game_gets_its_api_back_after_restart(env):
    client, fake = env
    login(client, **ADMIN)
    game_id = add_player(client, fake)["game_id"]
    GAMES.pop(game_id)  # jak po restarcie serwera: gra wraca z bazy
    fake.apis.clear()
    assert client.get(f"/api/games/{game_id}").status_code == 200
    assert fake.apis[-1][1] == {"api_base": "http://llm.example/v1", "api_key": "sk-tajny-klucz"}
    assert game_id in app.state.images.disabled


def test_preparation_retries_when_model_does_not_answer(env):
    client, fake = env
    login(client, **ADMIN)
    fake.responses.extend([LLMError("Timeout: Request timed out"), world_json()])
    client.post("/api/admin/users", json=PLAYER)
    user = wait_ready(client, "ania")
    assert user["status"] == "ready" and user["error"] is None


def test_failed_preparation_can_be_retried(env):
    client, fake = env
    login(client, **ADMIN)
    fake.responses.extend([LLMError("Timeout")] * admin.PREPARE_ATTEMPTS)
    client.post("/api/admin/users", json=PLAYER)
    user = wait_ready(client, "ania")
    assert user["status"] == "failed" and user["error"] and user["game_id"] is None
    fake.responses.clear()
    fake.responses.append(world_json())
    assert client.post("/api/admin/users/ania/game").status_code == 200
    assert wait_ready(client, "ania")["status"] == "ready"


def test_interrupted_preparation_shows_as_failed(env):
    client, _ = env
    login(client, **ADMIN)
    app.state.store.add_user("bartek", accounts.hash_password("haslo-bartka"), {"world_id": "zaginiona_korona"}, None)
    user = next(u for u in client.get("/api/admin/users").json() if u["login"] == "bartek")
    assert user["status"] == "failed" and "Ponów" in user["error"]


def test_validation_and_duplicates(env):
    client, fake = env
    login(client, **ADMIN)
    assert client.post("/api/admin/users", json={**PLAYER, "login": "administrator"}).status_code == 422
    assert client.post("/api/admin/users", json={**PLAYER, "login": "zły login!"}).status_code == 422
    assert client.post("/api/admin/users", json={**PLAYER, "world_idea": ""}).status_code == 422
    assert client.post("/api/admin/users", json={**PLAYER, "image_kind": "dvn"}).status_code == 422
    add_player(client, fake)
    assert client.post("/api/admin/users", json=PLAYER).status_code == 409


def test_password_change_and_delete_log_player_out(env):
    client, fake = env
    login(client, **ADMIN)
    add_player(client, fake)
    player = TestClient(app)
    login(player, "ania", "haslo-ani")
    assert player.get("/api/me").status_code == 200
    assert client.post("/api/admin/users/ania/password", json={"password": "nowe-haslo"}).status_code == 200
    assert player.get("/api/me").status_code == 401
    assert login(player, "ania", "nowe-haslo").status_code == 303
    assert client.delete("/api/admin/users/ania").status_code == 200
    assert player.get("/api/me").status_code == 401


def test_password_hash_and_encryption():
    stored = accounts.hash_password("tajne")
    assert stored.startswith("scrypt$") and accounts.check_password("tajne", stored)
    assert not accounts.check_password("inne", stored) and not accounts.check_password("tajne", "zepsute")
    token = accounts.encrypt({"klucz": "wartość"})
    assert accounts.decrypt(token) == {"klucz": "wartość"} and "wartość" not in token
    broken = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(accounts.DecryptError):
        accounts.decrypt(broken)
