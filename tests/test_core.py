"""Testy rdzenia gry: stan świata, pamięć, prompt, silnik."""

import json

import pytest

from app.core.context import build_messages, prompt_version
from app.core.engine import GameEngine, extract_json, normalize_location
from app.core.memory import FullHistory, SlidingWindow
from app.core.schemas import NarratorResponse, Scene, StateUpdate
from app.core.state import WorldState
from app.core.world import Fact, WorldNotFound, load_world
from app.llm.fake import FakeLLM
from app.storage.db import Store

WORLD = load_world("zaginiona_korona")


def response(location_id="tavern") -> NarratorResponse:
    return NarratorResponse(narration="...", scene=Scene(location_id=location_id, description="opis"))


def test_world_loads_and_rejects_bad_ids():
    assert WORLD.start_location == "tavern"
    assert any(f.immutable for f in WORLD.facts)
    with pytest.raises(WorldNotFound):
        load_world("../../etc/passwd")


def test_state_rejects_immutable_and_updates_mutable():
    state = WorldState([
        Fact(entity="miecz", attribute="materiał", value="srebrny", immutable=True),
        Fact(entity="bohater", attribute="monety", value="12"),
    ])
    accepted, rejected = state.apply([
        StateUpdate(entity="Miecz", attribute="Materiał", value="złoty"),    # wielkość liter bez znaczenia
        StateUpdate(entity="miecz", attribute="materiał", value="Srebrny"),  # ta sama wartość: brak zmiany
        StateUpdate(entity="bohater", attribute="monety", value="7"),
        StateUpdate(entity="kupiec", attribute="imię", value="Odrin"),       # nowy fakt
    ])
    assert len(rejected) == 1 and rejected[0].update.value == "złoty"
    assert len(accepted) == 2
    values = {(f.entity, f.attribute): f.value for f in state.facts()}
    assert values[("miecz", "materiał")] == "srebrny"
    assert values[("bohater", "monety")] == "7"
    assert values[("kupiec", "imię")] == "Odrin"


def test_extract_json_handles_fences_and_think_blocks():
    assert json.loads(extract_json('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(extract_json('<think>{nie to}</think> {"a": 2}')) == {"a": 2}
    with pytest.raises(ValueError):
        extract_json("brak jsona")


def test_normalize_location():
    assert normalize_location(" Old Tavern ") == "old_tavern"
    assert normalize_location("!!!") == "unknown"


def test_memory_window_keeps_last_n_turns():
    full, window = FullHistory(), SlidingWindow(3)
    for i in range(10):
        full.record(f"akcja {i}", response())
        window.record(f"akcja {i}", response())
    assert len(full.history()) == 20
    hist = window.history()
    assert len(hist) == 6 and hist[0]["content"] == "akcja 7"


def test_prompt_contains_state_only_when_enabled():
    state = WorldState(WORLD.facts)
    kwargs = {"current_location": "tavern", "known_locations": {"tavern": "Karczma"}}
    with_state = build_messages(WORLD, state, FullHistory(), "Hej", state_in_prompt=True, **kwargs)
    without = build_messages(WORLD, state, FullHistory(), "Hej", state_in_prompt=False, **kwargs)
    assert "miecz.materiał = srebrny (NIEZMIENNE)" in with_state[0]["content"]
    assert "srebrny" not in without[0]["content"]
    assert "Gracz jest w lokacji: tavern" in without[0]["content"]
    assert with_state[-1] == {"role": "user", "content": "Hej"}
    assert len(prompt_version()) == 8


@pytest.mark.anyio
async def test_engine_plays_turns_and_logs_them(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    fake = FakeLLM([
        json.dumps({"narration": "Wychodzisz.", "scene": {"location_id": "Old Inn", "description": "gospoda"},
                    "state_updates": [{"entity": "miecz", "attribute": "materiał", "value": "złoty"}]}),
        json.dumps({"narration": "Wracasz.", "scene": {"location_id": "tavern", "description": "karczma"}}),
    ])
    game = GameEngine(WORLD, fake, history="window", window=1, store=store)
    first = await game.step("Idę do gospody")
    assert first.location == "old_inn" and "old_inn" in game.known_locations
    assert len(first.rejected_updates) == 1
    second = await game.step("Wracam do karczmy")
    assert second.t == 2
    # okno = 1 tura: w drugim wywołaniu jest system + 1 tura (2 wiadomości) + nowa akcja
    assert len(fake.calls[1]) == 4

    rows = store.turns(game.game_id)
    assert [r["t"] for r in rows] == [1, 2]
    assert rows[0]["location_id"] == "Old Inn" and rows[0]["location"] == "old_inn"
    assert json.loads(rows[0]["rejected_updates"])[0]["update"]["value"] == "złoty"
