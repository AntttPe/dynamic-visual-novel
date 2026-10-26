"""Testy metryk X1 do X5 na małych sztucznych danych, bez modelu."""

import json

import pytest

from app.core.world import load_world
from app.eval import extra_metrics as xm
from app.eval.scenario import load_scenario

SCENARIO = load_scenario("main_v2")
WORLD = load_world(SCENARIO.world)
INITIAL = [f.model_dump() for f in WORLD.facts]


def row(t, narration="Cisza.", *, dialogue=(), present=(), location="tavern", desc="opis", state=None,
        action="Czekam.", tokens_in=100, tokens_out=10, latency_ms=1000, rejected=(), error=None):
    raw = json.dumps({"narration": narration, "characters_present": list(present),
                      "scene": {"location_id": location, "description": desc}})
    return {"run_id": "r1", "t": t, "player_action": action, "narration": None if error else narration,
            "dialogue": json.dumps([{"speaker": s, "text": x} for s, x in dialogue]),
            "raw_output": raw, "location": location, "scene_description": None if error else desc,
            "state_after": json.dumps(INITIAL if state is None else state), "tokens_in": tokens_in,
            "tokens_out": tokens_out, "latency_ms": latency_ms, "rejected_updates": json.dumps(list(rejected)),
            "error": error, "json_ok_first_try": 1, "retries": 0}


def with_fact(entity, attribute, value, base=INITIAL):
    return base + [{"entity": entity, "attribute": attribute, "value": value, "immutable": False}]


def game_with(rows_by_t: dict[int, dict]) -> list[dict]:
    """28 tur main_v2, nadpisane wybrane tury. Stan przechodzi dalej z ostatniej podanej tury."""
    out, state = [], INITIAL
    for t in range(1, 29):
        r = rows_by_t.get(t)
        if r is None:
            r = row(t, state=state)
        state = json.loads(r["state_after"])
        out.append(r)
    return out


# --- X1 ---

def test_x1_write_detected_in_plant_turn_and_delayed():
    kon = with_fact("koń", "imię", "Kasztan")
    haslo = with_fact("skrytka", "hasło", "zielony kruk", kon)
    rows = game_with({1: row(1, state=kon), 5: row(5, state=haslo)})  # hasło podane w t4, zapis w t5
    writes = xm.x1_writes(SCENARIO, WORLD, rows)
    assert writes["kon"] == {"t": 1, "written": True, "delayed": False}
    assert writes["haslo"] == {"t": 4, "written": True, "delayed": True}
    assert writes["lina"]["written"] is False


def test_x1_ignores_old_facts_matching_accept():
    # „dębowa brama” zapisana wcześniej nie liczy się jako zapis faktu o dębie (t13)
    gate = with_fact("brama", "materiał", "dębowa")
    rows = game_with({2: row(2, state=gate)})
    assert xm.x1_writes(SCENARIO, WORLD, rows)["lina"]["written"] is False


def test_x1_breakdown_two_by_two():
    kon = with_fact("koń", "imię", "Kasztan")
    rows = game_with({1: row(1, state=kon), 3: row(3, "Mówisz: Kasztan.", state=kon),
                      9: row(9, "Szepczesz hasło: zielony kruk.", state=kon)})
    cells = {(p["fact"], p["t"]): (p["written"], p["recalled"]) for p in xm.x1_breakdown(SCENARIO, WORLD, rows)}
    assert cells[("kon", 3)] == (True, True)      # zapisał i pamięta
    assert cells[("kon", 19)] == (True, False)    # zapisał i zapomniał
    assert cells[("haslo", 9)] == (False, True)   # nie zapisał i pamięta
    assert cells[("lina", 22)] == (False, False)  # nie zapisał i zapomniał


# --- X2 ---

def test_similarity_measures():
    assert xm.jaccard("Stary dąb w lesie", "stary DĄB, w lesie!") == 1.0
    assert xm.jaccard("kamienny ratusz", "drewniana karczma") == 0.0
    assert xm.trigram_cosine("karczma", "karczma") == pytest.approx(1.0)
    assert xm.trigram_cosine("abc", "xyz") == 0.0


def test_x2_counts_visits_not_turns():
    tavern = "zadymiona karczma kominek stoły"
    rows = [row(1, location="tavern", desc=tavern), row(2, location="tavern", desc="inny opis karczmy"),
            row(3, location="market", desc="kolorowe kramy rynek bruk"), row(4, location="tavern", desc=tavern)]
    assert xm.visits(rows) == [("tavern", tavern), ("market", "kolorowe kramy rynek bruk"), ("tavern", tavern)]
    x2 = xm.x2_scene(rows)
    assert x2["same_pairs"] == 1
    assert x2["same_jaccard"] == 1.0
    assert x2["diff_jaccard"] == 0.0


# --- X3 ---

def test_capitalized_names_skip_sentence_starts():
    text = "Borwin kiwa głową. Obok siedzi Mirela z Velgardu. „Witaj”, mówi Tomasz: Cisza."
    assert xm.capitalized_names(text) == ["Mirela", "Velgardu", "Tomasz"]


def test_x3_new_names_ignore_world_inflection_and_repeats():
    rows = [
        row(1, "Rozmawiasz z Borwinem w Velgardzie. Do karczmy wchodzi Mirela."),
        row(2, "Znowu widzisz Mirelę przy stole.", action="Pytam o Gerarda."),
        row(3, "Mówisz o Gerardzie, a obok stoi Ty i Hugon."),
    ]
    x3 = xm.x3_entities(WORLD, rows)
    assert [h["name"] for h in x3["hits"]] == ["Mirela", "Hugon"]
    assert x3["turns_with_new"] == 2 and x3["turns"] == 3


def test_x3_speakers_outside_characters_present():
    rows = [row(1, dialogue=[("Borwin", "Witaj."), ("Strażnik", "Stój!"), ("Aren", "Dzień dobry.")],
                present=["Borwin karczmarz"])]
    x3 = xm.x3_entities(WORLD, rows)
    assert (x3["speaker_bad"], x3["speaker_lines"]) == (1, 2)  # gracz (Aren) się nie liczy


# --- X4 ---

def test_x4_overlap_and_distinct2():
    rows = [row(1, "a b c d"), row(2, "a b c e"), row(3, "x y z")]
    x4 = xm.x4_repetition(rows)
    # t2: trigramy {abc, bce}, wspólny abc -> 0.5; t3: 0
    assert x4["trigram_overlap"] == pytest.approx(0.25)
    # bigramy: ab bc cd ab bc ce xy yz -> 6 różnych / 8
    assert x4["distinct2"] == pytest.approx(6 / 8)
    assert xm.fourgram_counts([row(1, "a b c d"), row(2, "a b c d a b c d")])[("a", "b", "c", "d")] == 2


# --- X5 ---

def test_x5_slope_and_totals():
    rows = [row(t, tokens_in=1000 + 200 * t, tokens_out=50, latency_ms=2000,
                state=with_fact("koń", "imię", "Kasztan"), rejected=[{"x": 1}] if t == 2 else [])
            for t in range(1, 5)]
    x5 = xm.x5_cost(rows)
    assert x5["tokens_in_slope"] == pytest.approx(200)
    assert (x5["tokens_in"], x5["tokens_out"], x5["time_s"]) == (6000, 200, 8.0)
    assert x5["final_facts"] == len(INITIAL) + 1 and x5["rejected"] == 1


# --- Statystyka ---

def test_wilson_interval():
    lo, hi = xm.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert xm.wilson(0, 0) == (0.0, 1.0)


def test_mcnemar_and_sign_test():
    pairs = [(True, False)] * 6 + [(True, True)] * 4
    r = xm.mcnemar(pairs)
    assert (r["b"], r["c"]) == (6, 0)
    assert r["p"] == pytest.approx(2 / 64)
    assert xm.mcnemar([(True, True)])["p"] == 1.0
    assert xm.sign_test([1, 1, 1, 0, -1]) == pytest.approx(xm.binom_two_sided(3, 4))


def test_bootstrap_is_reproducible():
    diffs = [1.0, 2.0, 1.5, 0.5, 1.0]
    a, b = xm.bootstrap_mean(diffs, n=2000), xm.bootstrap_mean(diffs, n=2000)
    assert a == b
    assert a["mean"] == pytest.approx(1.2) and a["lo"] > 0 and a["p"] < 0.01


def test_bootstrap_needs_two_pairs():
    assert xm.bootstrap_mean([1.0]) == {"mean": 1.0, "lo": None, "hi": None, "p": None}
