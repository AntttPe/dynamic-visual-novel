"""Testy pomiaru KV cache i zapisu TTFT (bez modelu)."""

import csv
import json
import sqlite3

import pytest

from app.core.engine import GameEngine
from app.core.world import load_world
from app.eval import kv_cache
from app.llm.base import LLMError, LLMResult
from app.storage.db import Store

WORLD = load_world("zaginiona_korona")
OK = json.dumps({"narration": "n", "scene": {"location_id": "tavern", "description": "d"}})


def game_turns(n=10, size=300):
    """Tury jak z bazy: prompt kończy się wiadomością gracza, plus odpowiedź narratora."""
    system = {"role": "system", "content": "S" * 300}
    return [{"prompt": [system, {"role": "user", "content": f"gracz {i} " + "x" * size}],
             "raw_output": f"narrator {i} " + "y" * size} for i in range(n)]


class TimedLLM:
    """Model na niby, który zgłasza TTFT jak przy strumieniowaniu."""

    def __init__(self, fail_times=0, model="fake/timed"):
        self.model = model
        self.calls = []
        self.fail_times = fail_times

    async def complete(self, messages, **kwargs):
        if self.fail_times:
            self.fail_times -= 1
            raise LLMError("VPN")
        self.calls.append(messages)
        return LLMResult(text=OK, tokens_in=len(messages) * 100, ttft_ms=12.5, first_answer_ms=20.0, latency_ms=30.0)


def test_conversation_grows_to_target_and_ends_with_player():
    turns = game_turns()
    messages, follow_up = kv_cache.build_conversation(turns, 600)
    assert kv_cache.estimate_tokens(messages) >= 600
    assert messages[0]["role"] == "system" and messages[-1]["role"] == "user"
    assert [m["role"] for m in messages[1:]] == ["user", "assistant"] * ((len(messages) - 2) // 2) + ["user"]
    # dopisek to odpowiedź na ostatnią wiadomość i kolejna wiadomość gracza, czyli następna tura full_cached
    k = (len(messages) - 2) // 2
    assert follow_up == [{"role": "assistant", "content": turns[k]["raw_output"]},
                         {"role": "user", "content": turns[k + 1]["prompt"][-1]["content"]}]


def test_too_short_game_is_reported():
    with pytest.raises(SystemExit):
        kv_cache.build_conversation(game_turns(n=2), 100_000)


def test_scenarios_share_prefix_only_where_expected():
    messages, follow_up = kv_cache.build_conversation(game_turns(), 600)
    p = kv_cache.scenario_prompts(messages, follow_up)
    assert list(p) == ["cold", "warm", "append", "invalidate"]
    assert p["warm"] == p["cold"]
    assert p["append"][:len(p["cold"])] == p["cold"] and len(p["append"]) == len(p["cold"]) + 2
    assert p["invalidate"][0] != p["cold"][0] and p["invalidate"][1:] == p["cold"][1:]
    # każde powtórzenie zaczyna od nowego znacznika, więc „cold” nie trafia w cache poprzedniego
    assert kv_cache.scenario_prompts(messages, follow_up)["cold"][0] != p["cold"][0]
    assert messages[0]["content"] == "S" * 300  # oryginał bez zmian


@pytest.mark.anyio
async def test_run_writes_csv_resumes_and_summarizes(tmp_path):
    out = tmp_path / "kv.csv"
    llm = TimedLLM()
    failed = await kv_cache.run(["fake/a"], [600, 1200], 2, game_turns(), out, tag="t", pause_s=0,
                                client_factory=lambda m: llm)
    assert failed == 0 and len(llm.calls) == 2 * 2 * 4
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 16 and {r["scenario"] for r in rows} == set(kv_cache.SCENARIOS)
    assert all(r["ttft_ms"] == "12.5" for r in rows)

    # druga taka sama komenda nic nie wysyła, a nowe powtórzenie dokłada tylko swoje wiersze
    again = TimedLLM()
    await kv_cache.run(["fake/a"], [600, 1200], 3, game_turns(), out, tag="t", pause_s=0,
                       client_factory=lambda m: again)
    assert len(again.calls) == 2 * 4

    table = kv_cache.summary(out, "t")
    assert "| a | 0.6k |" in table and "| 3 |" in table and "1.0x" in table


@pytest.mark.anyio
async def test_run_retries_after_errors_and_counts_failures(tmp_path):
    out = tmp_path / "kv.csv"
    flaky = TimedLLM(fail_times=1)
    failed = await kv_cache.run(["fake/a"], [600], 1, game_turns(), out, pause_s=0, backoff_s=(0.01,),
                                client_factory=lambda m: flaky)
    assert failed == 0 and len(flaky.calls) == 4

    dead = TimedLLM(fail_times=99)
    failed = await kv_cache.run(["fake/b"], [600], 1, game_turns(), out, pause_s=0, backoff_s=(0.01,),
                                client_factory=lambda m: dead)
    assert failed == 1
    assert not [r for r in csv.DictReader(out.open(encoding="utf-8")) if r["model"] == "fake/b"]


def test_pick_run_takes_longest_strata_game(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    for run_id, model, n in [("short", "openai/strata-big", 2), ("long", "openai/strata-big", 3),
                             ("other", "openai/large-reasoning", 5)]:
        store.create_run(run_id, {"mode": "eval", "world_id": "w", "model": model, "history": "window",
                                  "memory_window": 8, "state_in_prompt": True, "temperature": 0.7,
                                  "seed": 1, "prompt_version": "p"})
        with sqlite3.connect(store.path) as conn:
            for t in range(1, n + 1):
                conn.execute("INSERT INTO turns (run_id, t, created_at, player_action, prompt, raw_output,"
                             " json_ok_first_try, retries, tokens_in, tokens_out, latency_ms, location,"
                             " rejected_updates, state_after) VALUES (?,?,?,?,?,?,1,0,0,0,0,'l','[]','[]')",
                             (run_id, t, "now", "a", json.dumps(game_turns(1)[0]["prompt"]), "r"))
    assert kv_cache.pick_run(store.path) == "long"
    assert len(kv_cache.load_turns(store.path, "long")) == 3


@pytest.mark.anyio
async def test_engine_saves_ttft_of_first_attempt(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    engine = GameEngine(WORLD, TimedLLM(), store=store)
    await engine.step("Rozglądam się.")
    row = store.turns(engine.game_id)[0]
    assert (row["ttft_ms"], row["first_answer_ms"]) == (12.5, 20.0)


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE turns (run_id TEXT, t INTEGER)")
    Store(path)
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(turns)")}
    assert {"tokens_cached", "ttft_ms", "first_answer_ms"} <= cols
