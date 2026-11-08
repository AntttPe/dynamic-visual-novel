"""Tła lokacji w grze i serwer obrazów. Bez GPU: model na niby i serwer na losowym porcie."""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

BENCH = Path(__file__).resolve().parent.parent / "bench" / "images" / "consistency"
sys.path.insert(0, str(BENCH))

from models import FakeAdapter
from serve import ImageServer, watch_idle

from app.core.world import Fact
from app.images import (
    TALKING,
    BackgroundImages,
    HttpImageClient,
    SceneCast,
    location_seed,
    scene_prompt,
    visual_text,
)
from app.llm.fake import FakeLLM
from app.main import app
from app.storage.db import Store


class FakeImages:
    def __init__(self, fail_times: int = 0):
        self.calls: list[tuple[str, int]] = []
        self.models: list[str | None] = []
        self.fail_times = fail_times

    async def generate(self, prompt: str, seed: int, refs=(), model=None) -> tuple[bytes, str]:
        self.calls.append((prompt, seed, list(refs)))
        self.models.append(model)
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("tunel wyłączony")
        return b"png-bytes", "fake-model"


def narrator(location_id: str, description: str = "opis narratora", characters: list[str] | None = None) -> str:
    return json.dumps({"narration": "Idziesz.", "dialogue": [],
                       "scene": {"location_id": location_id, "description": description},
                       "state_updates": [], "characters_present": characters or []})


@pytest.fixture
def game_env(tmp_path):
    """Klient API z jedną pętlą asyncio (with), żeby zadania w tle dokończyły pracę."""
    llm, images = FakeLLM(), FakeImages()
    old = app.state.llm_factory, app.state.store, app.state.images
    store = Store(tmp_path / "test.sqlite")
    app.state.llm_factory = lambda model, world: llm
    app.state.store = store
    app.state.images = BackgroundImages(images, tmp_path / "images", store, "STYL")
    with TestClient(app) as client:
        yield client, llm, images, store
    app.state.llm_factory, app.state.store, app.state.images = old


def wait(client, game_id: str, location: str) -> dict:
    for _ in range(200):
        status = client.get(f"/api/games/{game_id}/image", params={"location": location}).json()
        if status["status"] != "pending":
            return status
        time.sleep(0.01)
    raise AssertionError("tło nie powstało")


def wait_scene(client, game_id: str, t: int) -> dict:
    for _ in range(200):
        status = client.get(f"/api/games/{game_id}/scene", params={"t": t}).json()
        if status["status"] != "pending":
            return status
        time.sleep(0.01)
    raise AssertionError("scena nie powstała")


def test_background_per_location_and_scene_per_turn(game_env):
    client, llm, images, store = game_env
    game_id = client.post("/api/games", json={"seed": 7}).json()["game_id"]
    status = wait(client, game_id, "tavern")
    assert status["status"] == "ready"
    assert client.get(status["url"]).content == b"png-bytes"

    llm.responses = [narrator("tavern", "inny opis karczmy"), narrator("mroczna piwnica!", "piwnica z beczkami")]
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "szukam korony"}).status_code == 200
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "schodzę"}).status_code == 200
    scene = wait_scene(client, game_id, 2)
    assert scene["status"] == "ready"
    assert client.get(scene["url"]).content == b"png-bytes"
    assert wait_scene(client, game_id, 1)["status"] == "ready"

    assert len(images.calls) == 5  # tło, portret bohatera, scena, nowe tło i scena: powrót nie zamawia nowego tła
    prompts = [c[0] for c in images.calls]
    assert prompts[0].startswith("STYL zadymiona drewniana karczma")  # stały opis ze świata
    assert "piwnica z beczkami" in next(p for p in prompts if p.startswith("STYL piwnica"))
    scene_1 = next(c for c in images.calls if "szukam korony" in c[0])
    assert scene_1[1] == location_seed(7, "tavern") + 1
    assert "zadymiona drewniana karczma" in scene_1[0]  # miejsce ze świata, a nie z opisu narratora
    assert "Idziesz." in scene_1[0]
    assert scene_1[2] == [b"png-bytes", b"png-bytes"]  # scena rysowana na podstawie tła i portretu bohatera

    rows = store.images(game_id)
    assert sorted((r["kind"], r["location_id"], r["t"], r["status"]) for r in rows) == [
        ("background", "mroczna_piwnica", 2, "ready"), ("background", "tavern", 0, "ready"),
        ("portrait", "aren wędrowny najemnik", 0, "ready"),
        ("scene", "mroczna_piwnica", 2, "ready"), ("scene", "tavern", 1, "ready")]


def test_game_uses_selected_image_generator(game_env):
    client, _, images, _ = game_env
    game = client.post("/api/games", json={"image_model": "qwen-image-21-turbo"}).json()
    assert game["image_model"] == "qwen-image-21-turbo"
    assert wait(client, game["game_id"], "tavern")["status"] == "ready"
    assert set(images.models) == {"qwen-image-21-turbo"}
    assert client.get(f"/api/games/{game['game_id']}").json()["image_model"] == "qwen-image-21-turbo"


def test_default_and_unknown_image_generator(game_env):
    client, _, _, _ = game_env
    assert client.post("/api/games", json={}).json()["image_model"] == "flux2-klein-4b"
    assert client.post("/api/games", json={"image_model": "nie-ma-takiego"}).status_code == 422


def test_portrait_drawn_once_and_used_in_later_scenes(game_env):
    client, llm, images, store = game_env
    game_id = client.post("/api/games", json={"seed": 7}).json()["game_id"]
    llm.responses = [narrator("tavern", characters=["Borwin", "Aren"]),
                     narrator("tavern", characters=["borwin karczmarz", "Straż", "Kupiec", "Żebrak"])]
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "idę do lady"}).status_code == 200
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "siadam"}).status_code == 200
    assert wait_scene(client, game_id, 2)["status"] == "ready"

    rows = store.images(game_id)
    assert sorted(r["location_id"] for r in rows if r["kind"] == "portrait") == [
        "aren wędrowny najemnik", "borwin", "straż"]
    borwin = next(c for c in images.calls if "karczmarz, rudy" in c[0] or "rudy, jednooki, karczmarz" in c[0])
    assert borwin[2] == []  # portret powstaje bez obrazów wejściowych
    scenes = [c for c in images.calls if len(c[2]) >= 2]
    assert len(scenes) == 2
    assert len(scenes[0][2]) == 3  # tło, bohater, Borwin
    assert len(scenes[1][2]) == 4  # tło i najwyżej 3 postacie


def test_turn_does_not_wait_for_failed_server_and_retries(game_env):
    client, llm, images, store = game_env
    images.fail_times = 1
    game_id = client.post("/api/games", json={}).json()["game_id"]
    assert wait(client, game_id, "tavern")["status"] == "failed"
    assert client.get(f"/api/games/{game_id}/image/file", params={"location": "tavern"}).status_code == 404
    assert client.get(f"/api/games/{game_id}/scene", params={"t": 1}).json() == {"status": "none"}

    llm.responses = [narrator("tavern")]
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "czekam"}).status_code == 200
    assert wait_scene(client, game_id, 1)["status"] == "ready"
    assert wait(client, game_id, "tavern")["status"] == "ready"
    assert [r["status"] for r in store.images(game_id)] == ["failed", "ready", "ready", "ready"]  # tło ponowione
    assert "ConnectionError" in store.images(game_id)[0]["error"]


def test_scene_prompt_describes_people_from_world_facts():
    facts = [Fact(entity="bohater", attribute="znak szczególny", value="blizna na lewej dłoni"),
             Fact(entity="borwin", attribute="wygląd", value="rudy, jednooki"),
             Fact(entity="borwin", attribute="zawód", value="karczmarz")]
    prompt = scene_prompt("STYL", "karczma", "Aren, wędrowny najemnik", facts, ["Borwin", "Aren", "Straż"],
                          "szukam korony", "Borwin marszczy brwi.")
    assert prompt == ("STYL karczma. Aren, wędrowny najemnik (blizna na lewej dłoni); "
                      "Borwin (rudy, jednooki); Straż. szukam korony. Borwin marszczy brwi.")


def test_people_stay_behind_when_player_leaves():
    cast = SceneCast("market")
    people = ["kobieta z węgierską szatą", "kupiec z kartonem owoców"]
    assert cast.update("market", people, "pytam ludzi") == (people, [])
    assert cast.update("forest", people, "idę stamtąd łowić ryby") == ([], people)  # narrator wymienia ich dalej
    assert cast.update("forest", people, "zarzucam wędkę") == ([], people)  # kolejna tura w tym samym miejscu
    assert cast.update("forest", ["rybak"], "witam się") == (["rybak"], [])  # nowa osoba w nowym miejscu
    assert cast.update("market", people, "wracam na rynek") == (people, [])  # powrót: znów tam są


@pytest.mark.parametrize("action", ["Wychodzę z Borwinem na rynek", "wychodzimy na rynek", "idę razem na rynek"])
def test_companions_go_with_player(action):
    cast = SceneCast("tavern")
    cast.update("tavern", ["Borwin"], "siadam przy ladzie")
    assert cast.update("market", ["Borwin"], action) == (["Borwin"], [])


def test_scene_after_leaving_shows_only_player(game_env):
    client, llm, images, store = game_env
    game_id = client.post("/api/games", json={"seed": 7}).json()["game_id"]
    llm.responses = [narrator("market", characters=["Kupiec z owocami"]),
                     narrator("forest", characters=["Kupiec z owocami"])]
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "idę na rynek"}).status_code == 200
    assert client.post(f"/api/games/{game_id}/turns", json={"action": "idę łowić ryby"}).status_code == 200
    assert wait_scene(client, game_id, 2)["status"] == "ready"
    scene = next(c for c in images.calls if "idę łowić ryby" in c[0])
    assert "Kupiec" not in scene[0]
    assert len(scene[2]) == 2  # tło i bohater, bez portretu kupca


@pytest.mark.parametrize("action, narration, expected", [
    ("kupuję jabłka", "Widzisz kram. Sprzedawca waży owoce.", "kupuję jabłka. Widzisz kram. Sprzedawca waży owoce."),
    ("on mówi, że da mi jabłka", "Borwin stoi obok. Czy jesteś gotów?", f"{TALKING} Borwin stoi obok."),
    ("idę", "„Stój!” Strażnik podnosi rękę. Rzekł: wracaj.", "idę. Strażnik podnosi rękę."),
    ("idę nad rzekę", "Woda szumi. Mewa krąży. Wiatr wieje.", "idę nad rzekę. Woda szumi. Mewa krąży."),
])
def test_visual_text_drops_speech(action, narration, expected):
    assert visual_text(action, narration) == expected


def test_images_off_without_server_url(tmp_path):
    images = BackgroundImages(None, tmp_path)
    images.request("g", "tavern", "opis", 1, 0)  # bez pętli asyncio i bez błędu
    assert images.status("g", "tavern") == {"status": "off"}
    assert images.path("g", "tavern") is None


def test_location_seed_is_stable_and_differs_between_locations():
    assert location_seed(5, "market") == location_seed(5, "market")
    assert location_seed(5, "market") != location_seed(5, "tavern")
    assert location_seed(None, "market") == location_seed(0, "market")


@pytest.fixture
def server():
    adapter = FakeAdapter()
    srv = ImageServer(adapter, 0, idle_s=3600)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, adapter, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_server_listens_only_on_loopback(server):
    srv, _, _ = server
    assert srv.server_address[0] == "127.0.0.1"


def test_http_client_gets_image_from_server(server):
    _, adapter, url = server
    data, model = asyncio.run(HttpImageClient(url, 5).generate("rynek", 123))
    assert data == b"fake 123 rynek"
    assert model == "fake"
    assert adapter.calls[0]["refs"] == []
    assert httpx.get(f"{url}/health").json() == {"status": "ok", "model": "fake"}


def test_http_client_sends_reference_images(server):
    _, adapter, url = server
    asyncio.run(HttpImageClient(url, 5).generate("scena", 5, [b"obraz"]))
    assert len(adapter.calls[0]["refs"]) == 1


@pytest.mark.parametrize("body", [
    b"nie json", b"[]", b'{"prompt": "x"}', b'{"prompt": "", "seed": 1}', b'{"prompt": "x", "seed": "1"}',
    b'{"prompt": "x", "seed": 1, "refs": ["@@"]}', b'{"prompt": "x", "seed": 1, "refs": 5}',
    b'{"prompt": "x", "seed": 1, "refs": ["", "", "", "", ""]}',
])
def test_server_rejects_bad_requests(server, body):
    _, adapter, url = server
    assert httpx.post(f"{url}/generate", content=body).status_code == 400
    assert adapter.calls == []


class NamedFake(FakeAdapter):
    def __init__(self, name: str, log: list[str]):
        super().__init__()
        self.name, self.log = name, log

    def load(self) -> None:
        self.log.append(f"load {self.name}")

    def unload(self) -> None:
        self.log.append(f"unload {self.name}")


def test_server_switches_model_on_request():
    log: list[str] = []
    srv = ImageServer(NamedFake("a", log), 0, 3600, factory=lambda n: NamedFake(n, log), models=("a", "b"))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/generate"
    try:
        assert httpx.post(url, json={"prompt": "x", "seed": 1, "model": "a"}).headers["x-image-model"] == "a"
        assert log == []  # ten sam model: bez przeładowania
        assert httpx.post(url, json={"prompt": "x", "seed": 1, "model": "b"}).headers["x-image-model"] == "b"
        assert log == ["unload a", "load b"]
        assert httpx.post(url, json={"prompt": "x", "seed": 1}).headers["x-image-model"] == "b"
        assert httpx.post(url, json={"prompt": "x", "seed": 1, "model": "c"}).status_code == 400
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_face_adapter_on_server_skips_location_image(server):
    srv, adapter, url = server
    adapter.location_refs = False
    payload = {"prompt": "x", "seed": 1, "refs": ["AAAA", "AAAA"]}
    assert httpx.post(f"{url}/generate", json=payload).status_code == 200
    assert len(adapter.calls[0]["refs"]) == 1


def test_server_reports_generation_error(server):
    srv, _, url = server

    def boom(*args):
        raise RuntimeError("CUDA out of memory")

    srv.adapter.generate = boom
    resp = httpx.post(f"{url}/generate", json={"prompt": "x", "seed": 1})
    assert resp.status_code == 500
    assert "out of memory" in resp.json()["error"]


def test_server_stops_when_idle():
    srv = ImageServer(FakeAdapter(), 0, idle_s=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    watch_idle(srv, poll_s=0.01)
    thread.join(timeout=5)
    srv.server_close()
    assert not thread.is_alive()
