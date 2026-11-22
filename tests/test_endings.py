"""Koniec gry: wygrana, przegrana i limit tur. Tylko gra w przeglądarce, eksperymenty bez zmian."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.context import prompt_version
from app.core.engine import NARRATOR_SCHEMA, GameEngine, GameOver
from app.core.world import load_world
from app.images import BackgroundImages
from app.llm.fake import FakeLLM
from app.main import app
from app.storage.db import Store

WORLD = load_world("zaginiona_korona")


def answer(status="ongoing", reason="", location_id="tavern"):
    return json.dumps({
        "narration": "Coś się dzieje.", "dialogue": [],
        "scene": {"location_id": location_id, "description": "karczma"},
        "state_updates": [], "characters_present": [],
        "outcome": {"status": status, "reason": reason},
    }, ensure_ascii=False)


@pytest.mark.anyio
async def test_win_ends_the_game():
    fake = FakeLLM([answer(), answer("won", "Korona wróciła do króla.")])
    game = GameEngine(WORLD, fake, endings=True)
    first = await game.step("Szukam korony")
    assert first.outcome.status == "ongoing" and not game.finished
    second = await game.step("Oddaję koronę królowi")
    assert second.outcome.status == "won" and game.finished
    with pytest.raises(GameOver):
        await game.step("Gram dalej")


@pytest.mark.anyio
async def test_turn_limit_ends_with_loss():
    game = GameEngine(WORLD, FakeLLM([answer(), answer()]), endings=True, max_turns=2)
    await game.step("Raz")
    assert not game.finished
    last = await game.step("Dwa")
    assert last.outcome.status == "lost" and "limit tur (2)" in last.outcome.reason


@pytest.mark.anyio
async def test_win_on_last_turn_is_still_a_win():
    game = GameEngine(WORLD, FakeLLM([answer("won", "Udało się.")]), endings=True, max_turns=1)
    assert (await game.step("Oddaję koronę")).outcome.status == "won"


@pytest.mark.anyio
async def test_prompt_has_conditions_and_turn_counter():
    fake = FakeLLM([answer()])
    game = GameEngine(WORLD, fake, endings=True, max_turns=5)
    await game.step("Rozglądam się")
    system = fake.calls[0][0]["content"]
    assert WORLD.win_condition in system and WORLD.lose_condition in system
    assert "limit 5 tur" in system
    assert system.rstrip().endswith("To jest tura 1 z 5.")
    assert game.config["prompt_version"].startswith(prompt_version() + "+end")


@pytest.mark.anyio
async def test_experiments_keep_old_prompt_and_schema():
    fake = FakeLLM([answer()])
    seen = {}
    complete = fake.complete

    async def spy(messages, **kw):
        seen.update(kw)
        return await complete(messages, **kw)

    fake.complete = spy
    game = GameEngine(WORLD, fake, mode="eval")
    record = await game.step("Rozglądam się")
    assert "# Koniec gry" not in fake.calls[0][0]["content"]
    assert seen["json_schema"] == NARRATOR_SCHEMA and "outcome" not in json.dumps(NARRATOR_SCHEMA)
    assert record.outcome is None and game.config["prompt_version"] == prompt_version()


@pytest.mark.anyio
async def test_full_cached_keeps_conditions_in_static_part():
    fake = FakeLLM([answer()])
    game = GameEngine(WORLD, fake, history="full_cached", endings=True, max_turns=3)
    await game.step("Rozglądam się")
    system, user = fake.calls[0][0]["content"], fake.calls[0][-1]["content"]
    assert "# Koniec gry" in system and "To jest tura 1 z 3." in user


@pytest.fixture
def env(tmp_path):
    fake = FakeLLM()
    old = app.state.llm_factory, app.state.store, app.state.images
    app.state.llm_factory = lambda model, world, **api: fake
    app.state.store = Store(tmp_path / "test.sqlite")
    app.state.images = BackgroundImages(None, tmp_path / "images")
    yield TestClient(app), fake
    app.state.llm_factory, app.state.store, app.state.images = old


def test_api_reports_end_and_blocks_further_turns(env):
    client, fake = env
    fake.responses = [answer("lost", "Bohater wpadł do lochu na zawsze.")]
    game = client.post("/api/games", json={"max_turns": 10}).json()
    assert game["max_turns"] == 10 and game["outcome"]["status"] == "ongoing"
    assert game["world"]["win_condition"] == WORLD.win_condition
    resp = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Obrażam króla"})
    assert resp.json()["outcome"] == {"status": "lost", "reason": "Bohater wpadł do lochu na zawsze."}
    assert client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Uciekam"}).status_code == 409
    assert client.get(f"/api/games/{game['game_id']}").json()["outcome"]["status"] == "lost"
    with sqlite3.connect(app.state.store.path) as conn:
        saved = conn.execute("SELECT outcome FROM turns WHERE run_id = ?", (game["game_id"],)).fetchone()[0]
    assert json.loads(saved)["status"] == "lost"


def test_narrator_without_outcome_field_keeps_game_going(env):
    client, fake = env
    fake.responses = [json.dumps({"narration": "x", "scene": {"location_id": "tavern", "description": "y"}})]
    game = client.post("/api/games", json={}).json()
    resp = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Czekam"})
    assert resp.json()["outcome"]["status"] == "ongoing"


@pytest.mark.anyio
async def test_easy_mode_adds_its_prompt_and_version():
    fake = FakeLLM([answer()])
    game = GameEngine(WORLD, fake, endings=True, difficulty="easy")
    await game.step("Rozglądam się")
    system = fake.calls[0][0]["content"]
    assert "# Poziom łatwy" in system and system.index("# Poziom łatwy") < system.index("# Aktualna sytuacja")
    assert "+easy" in game.config["prompt_version"] and game.config["difficulty"] == "easy"


@pytest.mark.anyio
async def test_normal_mode_and_experiments_have_no_easy_prompt():
    for game in (GameEngine(WORLD, FakeLLM([answer()]), endings=True),
                 GameEngine(WORLD, FakeLLM([answer()]), mode="eval", difficulty="easy")):
        await game.step("Rozglądam się")
        assert "# Poziom łatwy" not in game.llm.calls[0][0]["content"]
        assert "+easy" not in game.config["prompt_version"]
    with pytest.raises(ValueError):
        GameEngine(WORLD, FakeLLM(), endings=True, difficulty="hard")


@pytest.mark.anyio
async def test_hint_only_with_hints_on():
    with_hint = json.loads(answer())
    with_hint["hint"] = "Zapytaj Borwina o noc balu."
    easy = GameEngine(WORLD, FakeLLM([json.dumps(with_hint, ensure_ascii=False)]), endings=True, difficulty="easy")
    record = await easy.step("Rozglądam się")
    assert record.hint == "Zapytaj Borwina o noc balu."
    assert "`hint`" in easy.llm.calls[0][0]["content"]
    normal = GameEngine(WORLD, FakeLLM([json.dumps(with_hint, ensure_ascii=False)]), endings=True)
    assert (await normal.step("Rozglądam się")).hint is None
    empty = GameEngine(WORLD, FakeLLM([answer()]), endings=True, difficulty="easy")
    assert (await empty.step("Rozglądam się")).hint is None


def test_api_difficulty(env):
    client, _ = env
    game = client.post("/api/games", json={"difficulty": "easy"}).json()
    assert game["difficulty"] == "easy"
    assert client.post("/api/games", json={"difficulty": "hard"}).status_code == 422


def voiced_answer():
    return json.dumps({
        "narration": "Karczma milknie.", "scene": {"location_id": "tavern", "description": "karczma"},
        "dialogue": [{"speaker": "Borwin", "text": "Czego?", "gender": "male"},
                     {"speaker": "Ida", "text": "Spokojnie.", "gender": "female"},
                     {"speaker": "Ktoś", "text": "Hej!"}],
        "outcome": {"status": "ongoing", "reason": ""},
    }, ensure_ascii=False)


@pytest.mark.anyio
async def test_game_asks_for_speaker_gender_but_experiments_do_not():
    fake = FakeLLM([voiced_answer()])
    record = await GameEngine(WORLD, fake, endings=True).step("Wchodzę")
    assert "gender" in fake.calls[0][0]["content"]
    assert record.voices == {"Borwin": "male", "Ida": "female"}  # bez płci = lektor zgaduje w przeglądarce
    assert "gender" not in json.dumps(NARRATOR_SCHEMA)
    eval_record = await GameEngine(WORLD, FakeLLM([voiced_answer()]), mode="eval").step("Wchodzę")
    assert eval_record.voices is None


def test_api_returns_voices_also_after_restore(env):
    client, fake = env
    fake.responses = [voiced_answer()]
    game = client.post("/api/games", json={}).json()
    turn = client.post(f"/api/games/{game['game_id']}/turns", json={"action": "Wchodzę"}).json()["turn"]
    assert turn["voices"] == {"Borwin": "male", "Ida": "female"}
    from app.main import GAMES
    GAMES.clear()  # jak po restarcie serwera: gra wraca z bazy
    restored = client.get(f"/api/games/{game['game_id']}").json()
    assert restored["turns"][0]["voices"] == {"Borwin": "male", "Ida": "female"}
