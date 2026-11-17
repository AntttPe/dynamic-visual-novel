"""Zapisane gry: odtworzenie gry z bazy (po restarcie serwera albo do pokazania przebiegu).

Gra żyje w pamięci serwera, ale każda tura jest w data/dvn.sqlite. Stąd odtwarzamy pamięć narratora,
stan świata i listę tur, więc grę można obejrzeć tura po turze i grać dalej tym samym modelem.
"""

import json

from pydantic import ValidationError

from app.core.engine import GameEngine, extract_json
from app.core.schemas import (
    GameOutcome,
    HintNarratorResponse,
    NarratorResponse,
    PlayNarratorResponse,
    RejectedUpdate,
    StateUpdate,
    TurnRecord,
)
from app.core.world import Fact, World, WorldNotFound, load_world
from app.storage.db import Store


def saved_world(store: Store, run: dict) -> World | None:
    """Świat gry: z tabeli worlds (świat z pomysłu gracza) albo z app/worlds/*.yaml."""
    built = store.world(run["run_id"])
    if built:
        return World.model_validate(json.loads(built["world"]))
    try:
        return load_world(run["world_id"])
    except WorldNotFound:
        return None


def response_model(config: dict) -> type[NarratorResponse]:
    if config.get("difficulty") == "easy":
        return HintNarratorResponse
    return PlayNarratorResponse if "max_turns" in config else NarratorResponse


def turn_record(row: dict, model: type[NarratorResponse]) -> TurnRecord:
    parsed = None
    if row["error"] is None:
        try:
            parsed = model.model_validate_json(extract_json(row["raw_output"]))
        except (ValidationError, ValueError):
            parsed = None
    rejected = [RejectedUpdate(**x) for x in json.loads(row["rejected_updates"] or "[]")]
    refused = [x.update for x in rejected]
    proposed = [StateUpdate(**u) for u in json.loads(row["state_updates"] or "[]")]
    return TurnRecord(
        t=row["t"], player_action=row["player_action"], response=parsed, raw_output=row["raw_output"],
        json_ok_first_try=bool(row["json_ok_first_try"]), retries=row["retries"], tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"], tokens_cached=row["tokens_cached"] or 0, latency_ms=row["latency_ms"],
        ttft_ms=row["ttft_ms"], first_answer_ms=row["first_answer_ms"], prompt=json.loads(row["prompt"]),
        accepted_updates=[u for u in proposed if u not in refused], rejected_updates=rejected,
        location=row["location"], state_after=[Fact(**f) for f in json.loads(row["state_after"])],
        error=row["error"],
        outcome=GameOutcome.model_validate_json(row["outcome"]) if row["outcome"] else None,
        hint=(parsed.hint.strip() or None) if isinstance(parsed, HintNarratorResponse) else None,
    )


def load_game(store: Store, run_id: str, llm_factory) -> GameEngine | None:
    """Gra z bazy, gotowa do oglądania i dalszej gry. None, gdy nie ma takiej gry albo jej świata."""
    run = store.run(run_id)
    if not run or run["mode"] != "play":
        return None
    world = saved_world(store, run)
    if world is None:
        return None
    config = json.loads(run["config"])
    game = GameEngine(
        world, llm_factory(config["model"], world),
        history=config["history"], window=config["memory_window"], state_in_prompt=config["state_in_prompt"],
        temperature=config["temperature"], max_tokens=config.get("max_tokens"),
        json_retries=config.get("json_retries", 2), seed=config.get("seed"), store=store,
        game_id=run_id, create_run=False, endings="max_turns" in config,
        max_turns=config.get("max_turns"), difficulty=config.get("difficulty", "normal"),
    )
    game.config = config  # wersja promptu i model dokładnie jak przy tworzeniu gry
    rows = store.turns(run_id)
    game.restore(rows)
    model = response_model(config)
    game.turns = [turn_record(row, model) for row in rows]
    game._restored = 0  # tury są teraz w game.turns, numeracja liczy się od nich
    last = game.turns[-1].outcome if game.turns else None
    game.outcome = last or GameOutcome()
    return game
