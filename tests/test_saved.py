"""Zapisane gry: lista w menu i odtworzenie gry z bazy po restarcie serwera (bez modelu i bez GPU)."""

import json

from app.images import BackgroundImages
from app.main import GAMES, LOCKS, app
from tests.test_images import game_env, wait_scene  # noqa: F401  fixture z klientem, FakeLLM i obrazami na niby


def answer(location_id: str, hint: str = "", status: str = "ongoing", reason: str = "") -> str:
    return json.dumps({"narration": f"Jesteś w {location_id}.", "dialogue": [{"speaker": "Borwin", "text": "Witaj."}],
                       "scene": {"location_id": location_id, "description": "opis"},
                       "state_updates": [{"entity": "bohater", "attribute": "monety", "value": "3"}],
                       "characters_present": [], "hint": hint,
                       "outcome": {"status": status, "reason": reason}}, ensure_ascii=False)


def restart(tmp_path) -> None:
    """Jak restart serwera: gry znikają z pamięci, serwer obrazów jest wyłączony."""
    GAMES.clear()
    LOCKS.clear()
    app.state.images = BackgroundImages(None, tmp_path / "images", app.state.store, "STYL")


def test_saved_game_survives_restart_and_can_be_continued(game_env, tmp_path):
    client, llm, _, _ = game_env
    llm.responses = [answer("tavern", "Zapytaj Borwina."), answer("market", "Idź do bramy.")]
    game = client.post("/api/games", json={"difficulty": "easy", "max_turns": 5}).json()
    gid = game["game_id"]
    for action in ("Rozglądam się", "Idę na rynek"):
        assert client.post(f"/api/games/{gid}/turns", json={"action": action}).status_code == 200
    assert wait_scene(client, gid, 2)["status"] == "ready"
    before = client.get(f"/api/games/{gid}").json()

    restart(tmp_path)
    saved = client.get("/api/games").json()
    assert [g["game_id"] for g in saved] == [gid]
    assert saved[0]["turns"] == 2 and saved[0]["hints"] and saved[0]["title"] == "Zaginiona korona"
    assert client.get(saved[0]["thumb"]).content == b"png-bytes"

    after = client.get(f"/api/games/{gid}").json()
    assert [t["t"] for t in after["turns"]] == [1, 2]
    assert [t["hint"] for t in after["turns"]] == ["Zapytaj Borwina.", "Idź do bramy."]
    assert after["turns"][1]["accepted_updates"] == before["turns"][1]["accepted_updates"]
    assert after["location"] == "market" and after["state"] == before["state"]
    assert after["config"]["prompt_version"] == before["config"]["prompt_version"]
    scene = client.get(f"/api/games/{gid}/scene", params={"t": 2}).json()
    assert scene["status"] == "ready" and client.get(scene["url"]).content == b"png-bytes"

    llm.responses = [answer("castle_gate", status="won", reason="Korona wróciła.")]
    resp = client.post(f"/api/games/{gid}/turns", json={"action": "Oddaję koronę"})
    assert resp.status_code == 200
    assert resp.json()["turn"]["t"] == 3 and resp.json()["outcome"]["status"] == "won"
    history = [m for m in llm.calls[-1] if m["role"] == "user"]
    assert len(history) == 3  # pamięć narratora odtworzona: dwie wcześniejsze tury i nowa akcja


def test_unknown_game_is_404_and_empty_games_are_not_listed(game_env):
    client, _, _, _ = game_env
    client.post("/api/games", json={})  # gra bez tur
    assert client.get("/api/games").json() == []
    assert client.get("/api/games/nie_ma_takiej").status_code == 404


def test_prepared_custom_world_is_listed_without_turns(game_env):
    """Świat z pomysłu buduje się minutami, więc gotowa gra jest na liście, zanim ktoś zagra pierwszą turę."""
    from tests.test_world_builder import world_json

    client, llm, _, _ = game_env
    llm.responses = [world_json()]
    game_id = client.post("/api/games", json={"world_id": "custom", "world_idea": "detektywka w Krakowie"}).json()[
        "game_id"]
    client.post("/api/games", json={})  # gra na wbudowanym świecie bez tur dalej jest pomijana
    games = client.get("/api/games").json()
    assert [(g["game_id"], g["turns"], g["custom"]) for g in games] == [(game_id, 0, True)]
