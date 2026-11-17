"""Świat z pomysłu gracza. Bez modelu: odpowiedzi daje FakeLLM."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.world_builder import WorldBuildError, build_messages, build_world
from app.images import BackgroundImages
from app.llm.fake import FakeLLM
from app.main import app
from app.storage.db import Store
from tests.test_app import narrator_json

IDEA = "Cyberpunkowy Kraków w 2090 roku, detektywka szuka zaginionego androida."


def world_json(start="Neon Bar", **changes):
    draft = {
        "title": "Zaginiony android",
        "player": "Mira, detektywka",
        "setting": "Kraków w 2090 roku. Neon, deszcz i androidy. Bez magii.",
        "goal": "Odnaleźć zaginionego androida K-7.",
        "win_condition": "Mira przyprowadza K-7 do swojego biura.",
        "lose_condition": "Mira ginie albo K-7 zostaje zniszczony.",
        "rules": ["Nie ma magii.", "Androidy nie mogą kłamać ludziom."],
        "visual_style": "cyberpunk city in 2090, neon and rain",
        "start_location": start,
        "intro": "Siedzisz w barze Neon, a barman Jaro poleruje szklankę.",
        "locations": [
            {"id": "Neon Bar", "name": "Bar Neon", "description": "ciasny bar, neony, deszcz za szybą"},
            {"id": "neon_bar", "name": "Duplikat", "description": "to samo miejsce drugi raz"},
            {"id": "market", "name": "Targ elektroniki", "description": "stragany z częściami, kable, dym"},
        ],
        "facts": [
            {"entity": "Bohater", "attribute": "ekwipunek", "value": "pistolet, notes", "immutable": False},
            {"entity": "jaro", "attribute": "wygląd", "value": "łysy, metalowa szczęka", "immutable": True},
        ],
    }
    draft.update(changes)
    return json.dumps(draft, ensure_ascii=False)


def test_prompt_has_guideline_example_and_idea():
    messages = build_messages(IDEA)
    assert "Zaginiona korona" in messages[0]["content"]
    assert '"start_location": "tavern"' in messages[0]["content"]  # wzór jako JSON
    assert messages[1]["content"].endswith(IDEA)


@pytest.mark.anyio
async def test_build_world_normalizes_draft():
    built = await build_world(FakeLLM([world_json()]), IDEA)
    w = built.world
    assert w.id.startswith("custom_") and w.title == "Zaginiony android"
    assert w.win_condition == "Mira przyprowadza K-7 do swojego biura."
    assert [loc.id for loc in w.locations] == ["neon_bar", "market"]  # bez duplikatu, snake_case
    assert w.start_location == "neon_bar"
    assert {"entity": "bohater", "attribute": "ekwipunek", "value": "pistolet, notes",
            "immutable": False} in [f.model_dump() for f in w.facts]
    assert built.retries == 0 and built.raw_output


@pytest.mark.anyio
async def test_unknown_start_falls_back_to_first_location():
    built = await build_world(FakeLLM([world_json(start="nigdzie")]), IDEA)
    assert built.world.start_location == "neon_bar"


@pytest.mark.anyio
async def test_invalid_world_is_retried_then_reported():
    built = await build_world(FakeLLM(["to nie json", world_json()]), IDEA, retries=2)
    assert built.retries == 1
    with pytest.raises(WorldBuildError):
        await build_world(FakeLLM(["zły", '{"title": "bez reszty"}']), IDEA, retries=1)


@pytest.fixture
def env(tmp_path):
    fake = FakeLLM()
    old = app.state.llm_factory, app.state.store, app.state.images
    app.state.llm_factory = lambda model, world, **api: fake
    app.state.store = Store(tmp_path / "test.sqlite")
    app.state.images = BackgroundImages(None, tmp_path / "images")
    yield TestClient(app), fake
    app.state.llm_factory, app.state.store, app.state.images = old


def test_custom_world_game(env):
    client, fake = env
    fake.responses = [world_json(), narrator_json(location_id="market")]
    resp = client.post("/api/games", json={"world_id": "custom", "world_idea": IDEA, "model": "fake/x"})
    assert resp.status_code == 200
    game = resp.json()
    assert game["world"]["title"] == "Zaginiony android" and game["world"]["custom"] is True
    assert game["location"] == "neon_bar"
    assert game["config"]["world_id"].startswith("custom_")
    saved = app.state.store.world(game["game_id"])
    assert saved["idea"] == IDEA and saved["model"] == "fake/x"
    assert json.loads(saved["world"])["title"] == "Zaginiony android"

    turn = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Idę na targ"})
    assert turn.status_code == 200
    assert "Zaginiony android" in fake.calls[-1][0]["content"]  # narrator dostaje nowy świat


def test_custom_world_needs_idea_and_reports_bad_model_output(env):
    client, fake = env
    assert client.post("/api/games", json={"world_id": "custom"}).status_code == 422
    fake.responses = ["zły", "zły", "zły"]
    resp = client.post("/api/games", json={"world_id": "custom", "world_idea": IDEA, "model": "fake/x"})
    assert resp.status_code == 502 and "świata" in resp.json()["detail"]


def test_custom_world_in_demo_mode(env):
    client, _ = env
    game = client.post("/api/games", json={"world_id": "custom", "world_idea": IDEA, "model": "demo"}).json()
    assert game["world"]["title"] == "Własny świat (demo)"
    assert IDEA in game["world"]["setting"]
