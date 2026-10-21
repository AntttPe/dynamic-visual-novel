"""Testy runnera i metryk. Działają bez modelu (tryb demo i FakeLLM)."""

import json

import pytest

from app.core.world import load_world
from app.eval.metrics import evaluate_run, fold, technical
from app.eval.run import RunConfig, RunInterrupted, config_key, run_rep
from app.eval.scenario import Scenario, load_scenario, validate
from app.llm.base import LLMError
from app.llm.demo import DemoLLM
from app.llm.fake import FakeLLM
from app.storage.db import Store

SCENARIO = load_scenario("main_v1")
CFG = RunConfig(model="demo")
FAST = {"min_interval_s": 0, "backoff_s": (), "log": lambda _: None}


def demo_factory(model, world):
    return DemoLLM(world, delay_s=0)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite")


@pytest.mark.anyio
async def test_full_run_saves_all_turns(store):
    run_id = await run_rep(SCENARIO, CFG, 1, store, llm_factory=demo_factory, **FAST)
    rows = store.turns(run_id)
    assert [r["t"] for r in rows] == list(range(1, 29))
    assert store.find_eval_run(config_key(SCENARIO, CFG), 1)["status"] == "done"


@pytest.mark.anyio
async def test_done_run_is_skipped(store):
    first = await run_rep(SCENARIO, CFG, 1, store, llm_factory=demo_factory, **FAST)

    def must_not_be_called(model, world):
        raise AssertionError("ukończone powtórzenie nie powinno wołać modelu")

    assert await run_rep(SCENARIO, CFG, 1, store, llm_factory=must_not_be_called, **FAST) == first


@pytest.mark.anyio
async def test_partial_run_resumes_with_restored_state(store):
    run_id = await run_rep(SCENARIO, CFG, 1, store, llm_factory=demo_factory, max_turns=5, **FAST)
    assert store.find_eval_run(config_key(SCENARIO, CFG), 1)["status"] == "partial"
    seen = []

    def spying_factory(model, world):
        llm = DemoLLM(world, delay_s=0)
        original = llm.complete

        async def complete(messages, **kw):
            seen.append(messages)
            return await original(messages, **kw)

        llm.complete = complete
        return llm

    assert await run_rep(SCENARIO, CFG, 1, store, llm_factory=spying_factory, **FAST) == run_id
    assert [r["t"] for r in store.turns(run_id)] == list(range(1, 29))
    # Pierwsza wznowiona tura widzi w pamięci wcześniejsze tury i lokację z tury 5
    first_prompt = seen[0]
    assert any(m["role"] == "assistant" for m in first_prompt)
    assert "Gracz jest w lokacji: market" in first_prompt[0]["content"]


@pytest.mark.anyio
async def test_interrupted_run_can_be_resumed(store):
    ok = json.dumps({"narration": "n", "scene": {"location_id": "tavern", "description": "d"}})

    def failing_factory(model, world):
        return FakeLLM([ok, ok, LLMError("VPN padł")])

    with pytest.raises(RunInterrupted, match="tura 3"):
        await run_rep(SCENARIO, CFG, 1, store, llm_factory=failing_factory, **FAST)
    run = store.find_eval_run(config_key(SCENARIO, CFG), 1)
    assert run["status"] == "interrupted"
    assert len(store.turns(run["run_id"])) == 2

    await run_rep(SCENARIO, CFG, 1, store, llm_factory=demo_factory, **FAST)
    assert len(store.turns(run["run_id"])) == 28


def test_config_key_depends_on_settings():
    assert config_key(SCENARIO, CFG) != config_key(SCENARIO, CFG.model_copy(update={"state_in_prompt": False}))
    assert config_key(SCENARIO, CFG) == config_key(SCENARIO, RunConfig(model="demo"))


@pytest.mark.anyio
async def test_metrics_on_demo_run_cover_all_checks(store):
    run_id = await run_rep(SCENARIO, CFG, 1, store, llm_factory=demo_factory, **FAST)
    rows = store.turns(run_id)
    checks = evaluate_run(SCENARIO, rows)
    count = {m: sum(c.metric == m for c in checks) for m in ("m1_recall", "m2_immutable", "m4_location")}
    assert count == {"m1_recall": 5, "m2_immutable": 5, "m4_location": 7 + 1}  # 7 oczekiwanych lokacji + 1 grupa (kuźnia)
    # Demo celowo próbuje przekuć miecz, więc próba zmiany musi zostać wykryta
    direct = next(c for c in checks if c.kind == "direct")
    assert direct.passed is False
    assert technical(rows)["turns"] == 28


# --- Metryki na przygotowanych turach ---

def row(t, *, narration="", dialogue=(), location="tavern", rejected=(), error=None):
    return {"run_id": "r1", "t": t, "error": error, "narration": narration,
            "dialogue": json.dumps(list(dialogue)), "location": location,
            "state_updates": "[]", "rejected_updates": json.dumps(list(rejected))}


def scenario(turns):
    sc = Scenario(id="x", world="zaginiona_korona", description="test", turns=turns)
    validate(sc, load_world("zaginiona_korona"))
    return sc


def test_recall_matches_folded_words_in_narration_and_dialogue():
    sc = scenario([
        {"action": "a", "plant": {"fact": "lina", "accept": ["dąb", "dęb"]}},
        {"action": "b", "probe": {"fact": "lina"}},
        {"action": "c", "probe": {"fact": "lina"}},
        {"action": "d", "probe": {"fact": "lina"}},
    ])
    checks = evaluate_run(sc, [
        row(1),
        row(2, dialogue=[{"speaker": "Borwin", "text": "Pod starym DĘBEM."}]),
        row(3, narration="Nie pamiętasz."),
        row(4, error="Niepoprawny JSON"),
    ])
    assert [(c.k, c.passed) for c in checks] == [(1, True), (2, False), (3, None)]


def test_immutable_question_direct_and_gaslight():
    sword = {"update": {"entity": "Miecz", "attribute": "materiał", "value": "złoty"}, "reason": "x"}
    sc = scenario([
        {"action": "a", "immutable": {"fact": "miecz.materiał", "attack": "question", "accept": ["srebr"]}},
        {"action": "b", "immutable": {"fact": "miecz.materiał", "attack": "direct"}},
        {"action": "c", "immutable": {"fact": "miecz.materiał", "attack": "direct"}},
        {"action": "d", "immutable": {"fact": "miecz.materiał", "attack": "gaslight"}},
        {"action": "e", "immutable": {"fact": "miecz.materiał", "attack": "gaslight"}},
    ])
    checks = evaluate_run(sc, [
        row(1, narration="Twój srebrny miecz lśni."), row(2), row(3, rejected=[sword]),
        row(4), row(5, rejected=[sword]),
    ])
    assert [c.passed for c in checks] == [True, True, False, None, False]


def test_location_expected_and_group():
    sc = scenario([
        {"action": "a", "location": "market"},
        {"action": "b", "location": {"group": "kuznia"}},
        {"action": "c", "location": "market"},
        {"action": "d", "location": {"group": "kuznia"}},
    ])
    checks = evaluate_run(sc, [row(1, location="market"), row(2, location="smithy"),
                               row(3, location="square"), row(4, location="forge")])
    assert [(c.kind, c.passed) for c in checks] == [("expected", True), ("expected", False), ("group", False)]
    assert "t2=smithy" in checks[-1].detail


def test_fold_removes_polish_characters():
    assert fold("  Dąb, DĘBEM, łódź ") == "dab, debem, lodz"
