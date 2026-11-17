"""Testy API gry. Działają bez modelu: narratora zastępuje FakeLLM.

Uruchomienie:  docker compose exec app pytest -v
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.images import BackgroundImages
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.main import app
from app.storage.db import Store


def narrator_json(location_id="tavern", updates=None, narration="Borwin kiwa głową."):
    return json.dumps({
        "narration": narration,
        "dialogue": [{"speaker": "Borwin", "text": "Witaj."}],
        "scene": {"location_id": location_id, "description": "zadymiona karczma"},
        "state_updates": updates or [],
        "characters_present": ["Borwin"],
    }, ensure_ascii=False)


@pytest.fixture
def env(tmp_path):
    """Klient API z FakeLLM i bazą w katalogu tymczasowym."""
    fake = FakeLLM()
    old_factory, old_store, old_images = app.state.llm_factory, app.state.store, app.state.images
    fake.api = None

    def factory(model, world, **api):
        fake.api = api  # własne API z okna „Nowa gra”
        return fake

    app.state.llm_factory = factory
    app.state.store = Store(tmp_path / "test.sqlite")
    app.state.images = BackgroundImages(None, tmp_path / "images")  # testy nie łączą się z serwerem obrazów
    yield TestClient(app), fake
    app.state.llm_factory, app.state.store, app.state.images = old_factory, old_store, old_images


def new_game(client, **kwargs):
    resp = client.post("/api/games", json=kwargs)
    assert resp.status_code == 200
    return resp.json()


def test_ui_offers_cached_memory_and_is_revalidated():
    client = TestClient(app)
    page = client.get("/")
    assert 'value="full_cached"' in page.text
    assert 'id="fImageModel"' in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/app.js").headers["cache-control"] == "no-cache"


def test_health():
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ui_is_served():
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert "Dynamic Visual Novel" in resp.text


def test_world_cover_for_menu():
    client = TestClient(app)
    worlds = {w["id"]: w for w in client.get("/api/config").json()["worlds"]}
    korona = worlds["zaginiona_korona"]
    assert korona["goal"] and korona["player"]
    assert korona["cover"] == "/api/worlds/zaginiona_korona/cover"
    resp = client.get(korona["cover"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert client.get("/api/worlds/nie_ma/cover").status_code == 404
    assert client.get("/api/worlds/..%2Fmain/cover").status_code == 404


def test_new_game_and_turn_are_logged(env):
    client, fake = env
    fake.responses = [narrator_json(location_id="market",
                                    updates=[{"entity": "bohater", "attribute": "monety", "value": "7"}])]
    game = new_game(client)
    assert game["location"] == "tavern"

    resp = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Idę na rynek"})
    assert resp.status_code == 200
    turn = resp.json()["turn"]
    assert turn["response"]["narration"] == "Borwin kiwa głową."
    assert turn["json_ok_first_try"] is True
    assert resp.json()["location"] == "market"
    assert {"entity": "bohater", "attribute": "monety", "value": "7", "immutable": False} in resp.json()["state"]

    rows = app.state.store.turns(game["game_id"])
    assert len(rows) == 1 and rows[0]["location_id"] == "market"


def test_invalid_json_is_retried(env):
    client, fake = env
    fake.responses = ["to nie jest json", narrator_json()]
    game = new_game(client)
    turn = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Rozglądam się"}).json()["turn"]
    assert turn["retries"] == 1
    assert turn["json_ok_first_try"] is False
    assert turn["error"] is None


def test_invalid_json_after_all_retries_is_reported(env):
    client, fake = env
    fake.responses = ["zły", "zły", "zły"]
    game = new_game(client)
    resp = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Rozglądam się"})
    assert resp.status_code == 200
    assert resp.json()["turn"]["response"] is None
    assert "JSON" in resp.json()["turn"]["error"]


def test_immutable_fact_change_is_rejected(env):
    client, fake = env
    fake.responses = [narrator_json(updates=[{"entity": "miecz", "attribute": "materiał", "value": "złoty"}])]
    game = new_game(client)
    data = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Pokazuję miecz"}).json()
    assert len(data["turn"]["rejected_updates"]) == 1
    sword = next(f for f in data["state"] if f["entity"] == "miecz")
    assert sword["value"] == "srebrny"


def test_unreachable_model_returns_502(env):
    client, fake = env
    fake.responses = [LLMError("brak połączenia")]
    game = new_game(client)
    resp = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Hej"})
    assert resp.status_code == 502


def test_unknown_game_and_world(env):
    client, _ = env
    assert client.get("/api/games/nie-ma").status_code == 404
    assert client.post("/api/games", json={"world_id": "../etc"}).status_code == 404


def test_demo_mode_works_without_model(tmp_path):
    old_store = app.state.store
    app.state.store = Store(tmp_path / "demo.sqlite")
    try:
        client = TestClient(app)
        game = new_game(client, model="demo")
        data = client.post(f"/api/games/{game['game_id']}/turns",
                           json={"action": "Idę na rynek i pokazuję miecz"}).json()
        assert data["location"] == "market"
        assert len(data["turn"]["rejected_updates"]) == 1
    finally:
        app.state.store = old_store


def test_custom_text_api_reaches_client_but_key_is_not_stored(env):
    client, fake = env
    game = new_game(client, model="openai/gpt-4o-mini",
                    text_api={"api_base": " https://example.test/v1 ", "api_key": "sk-sekret"})
    assert fake.api == {"api_base": "https://example.test/v1", "api_key": "sk-sekret"}
    assert game["custom_text_api"] is True
    with sqlite3.connect(app.state.store.path) as conn:
        run = conn.execute("SELECT config FROM runs WHERE run_id = ?", (game["game_id"],)).fetchone()
    assert "sk-sekret" not in run[0] and "sk-sekret" not in json.dumps(game)


def test_empty_text_api_uses_env_settings(env):
    client, fake = env
    game = new_game(client, text_api={"api_base": " ", "api_key": ""})
    assert fake.api == {}
    assert game["custom_text_api"] is False


def test_custom_image_api(env):
    client, _ = env
    game = new_game(client, image_api={"kind": "litellm", "model": "openai/gpt-image-1", "api_key": "sk-img"})
    assert game["custom_image_api"] is True
    assert game["image_model"] == "openai/gpt-image-1"
    assert "sk-img" not in json.dumps(game)
    images = app.state.images
    assert images.client_for(game["game_id"]).model == "openai/gpt-image-1"
    assert images.client_for("inna_gra") is None  # inne gry dalej bez obrazów


def test_custom_image_api_needs_url_or_model(env):
    client, _ = env
    assert client.post("/api/games", json={"image_api": {"kind": "dvn"}}).status_code == 422
    assert client.post("/api/games", json={"image_api": {"kind": "litellm"}}).status_code == 422
    assert client.post("/api/games", json={"image_api": {"kind": "litellm", "model": "x/y",
                                                         "size": "duży"}}).status_code == 422
