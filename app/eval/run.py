"""Runner eksperymentów: przepuszcza scenariusz przez model, tura po turze.

Użycie (w kontenerze):
  python -m app.eval.run --model openai/large-reasoning --reps 3
  python -m app.eval.run --model demo --max-turns 5          # szybki test bez modelu

Ta sama komenda uruchomiona ponownie wznawia przerwane powtórzenia i pomija ukończone.
Używa tego samego silnika co gra (GameEngine), wyniki trafiają do data/dvn.sqlite.
"""

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from app import llm
from app.config import settings
from app.core.context import prompt_version
from app.core.engine import GameEngine
from app.core.world import World, load_world
from app.eval.scenario import Scenario, load_scenario
from app.storage.db import Store

# Przerwy między ponowieniami, gdy model nie odpowiada (sieć, VPN, przeciążony serwer).
# Razem około 14 minut, żeby zdążyć ponownie połączyć VPN bez przerywania badania.
BACKOFF_S = (10, 30, 60, 120, 300, 300)


class RunConfig(BaseModel):
    model: str
    history: str = "window"
    window: int = 8
    state_in_prompt: bool = True
    temperature: float = 0.7
    seed_base: int = 1000
    tag: str = ""


class RunInterrupted(Exception):
    """Model przestał odpowiadać. Uruchom tę samą komendę ponownie, żeby wznowić."""


def config_key(scenario: Scenario, cfg: RunConfig) -> str:
    """Identyfikator konfiguracji. Te same ustawienia = to samo badanie, więc można je wznawiać."""
    payload = {"scenario": scenario.id, "version": scenario.version, "prompt": prompt_version(),
               **cfg.model_dump()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


LLMFactory = Callable[[str, World], llm.LLMClient]


def default_factory(model: str, world: World) -> llm.LLMClient:
    return llm.make_client(model, world, settings)


async def run_rep(
    scenario: Scenario,
    cfg: RunConfig,
    rep: int,
    store: Store,
    *,
    llm_factory: LLMFactory = default_factory,
    max_turns: int | None = None,
    min_interval_s: float = 2.0,
    backoff_s: tuple[float, ...] = BACKOFF_S,
    log: Callable[[str], None] = print,
) -> str:
    """Rozgrywa (albo wznawia) jedno powtórzenie scenariusza. Zwraca run_id."""
    key = config_key(scenario, cfg)
    existing = store.find_eval_run(key, rep)
    if existing and existing["status"] == "done":
        log(f"[powt. {rep}] już ukończone, pomijam ({existing['run_id']})")
        return existing["run_id"]

    world = load_world(scenario.world)
    engine = GameEngine(
        world,
        llm_factory(cfg.model, world),
        history=cfg.history,
        window=cfg.window,
        state_in_prompt=cfg.state_in_prompt,
        temperature=cfg.temperature,
        max_tokens=settings.narrator_max_tokens,
        json_retries=settings.narrator_json_retries,
        seed=cfg.seed_base + rep,
        store=store,
        mode="eval",
        game_id=existing["run_id"] if existing else None,
        create_run=existing is None,
    )
    if existing:
        engine.restore(store.turns(engine.game_id))
    else:
        store.create_eval_run(engine.game_id, key, scenario.id, scenario.version, rep, cfg.tag)
    store.set_eval_status(engine.game_id, "running")

    turns = scenario.turns[:max_turns] if max_turns else scenario.turns
    start_at = engine._restored
    if start_at:
        log(f"[powt. {rep}] wznawiam od tury {start_at + 1}")

    for i in range(start_at, len(turns)):
        action = turns[i].action
        for attempt in range(len(backoff_s) + 1):
            started = time.perf_counter()
            try:
                record = await engine.step(action)
                break
            except llm.LLMError as e:
                if attempt == len(backoff_s):
                    note = f"tura {i + 1}: {str(e)[:300]}"
                    store.set_eval_status(engine.game_id, "interrupted", note)
                    raise RunInterrupted(note) from e
                log(f"[powt. {rep}] tura {i + 1}: model nie odpowiada, ponawiam za {backoff_s[attempt]} s")
                await asyncio.sleep(backoff_s[attempt])
        status = "JSON ok" if record.response else f"BŁĄD JSON ({record.error})"
        log(f"[powt. {rep}] tura {i + 1}/{len(turns)}  {record.latency_ms / 1000:5.1f} s  "
            f"{status}  lokacja: {record.location}")
        # Prosty limit zapytań (serwer instytutu: 30 na minutę)
        await asyncio.sleep(max(0.0, min_interval_s - (time.perf_counter() - started)))

    finished = len(turns) == len(scenario.turns)
    store.set_eval_status(engine.game_id, "done" if finished else "partial")
    return engine.game_id


async def run_all(scenario: Scenario, cfg: RunConfig, reps: int, store: Store, **kwargs) -> list[str]:
    return [await run_rep(scenario, cfg, rep, store, **kwargs) for rep in range(1, reps + 1)]


def main() -> None:
    p = argparse.ArgumentParser(description="Uruchamia scenariusz badawczy na wybranym modelu.")
    p.add_argument("--scenario", default="main_v2")
    p.add_argument("--model", default=settings.default_narrator_model)
    p.add_argument("--reps", type=int, default=3, help="liczba powtórzeń (różne seedy)")
    p.add_argument("--history", choices=["full", "window"], default=settings.memory_history)
    p.add_argument("--window", type=int, default=settings.memory_window)
    p.add_argument("--no-state", action="store_true", help="bez stanu świata w prompcie")
    p.add_argument("--temperature", type=float, default=settings.narrator_temperature)
    p.add_argument("--seed", type=int, default=1000, help="seed powtórzenia = seed + numer powtórzenia")
    p.add_argument("--tag", default="", help="nazwa eksperymentu, np. sprint1")
    p.add_argument("--max-turns", type=int, help="tylko pierwsze N tur (szybki test)")
    args = p.parse_args()

    scenario = load_scenario(args.scenario)
    cfg = RunConfig(model=args.model, history=args.history, window=args.window,
                    state_in_prompt=not args.no_state, temperature=args.temperature,
                    seed_base=args.seed, tag=args.tag)
    store = Store(Path(settings.data_dir) / "dvn.sqlite")
    print(f"Scenariusz {scenario.id} v{scenario.version} ({len(scenario.turns)} tur), model {cfg.model}, "
          f"pamięć {cfg.history}/{cfg.window}, stan w prompcie: {cfg.state_in_prompt}, "
          f"powtórzenia: {args.reps}, konfiguracja {config_key(scenario, cfg)}")
    try:
        asyncio.run(run_all(scenario, cfg, args.reps, store, max_turns=args.max_turns))
    except RunInterrupted as e:
        raise SystemExit(f"\nPrzerwano: {e}\nSprawdź VPN i uruchom tę samą komendę ponownie, żeby wznowić.")
    except KeyboardInterrupt:
        raise SystemExit("\nZatrzymano. Ta sama komenda wznowi od ostatniej zapisanej tury.") from None
    print(f"\nGotowe. Wyniki: python -m app.eval.report --scenario {scenario.id}")


if __name__ == "__main__":
    main()
