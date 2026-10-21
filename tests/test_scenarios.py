"""Testy formatu scenariuszy badawczych. Każdy plik w app/eval/scenarios musi być poprawny."""

import pytest

from app.core.world import load_world
from app.eval.scenario import (
    SCENARIOS_DIR,
    Scenario,
    ScenarioError,
    list_scenarios,
    load_scenario,
    summary,
    validate,
)

WORLD = load_world("zaginiona_korona")


@pytest.mark.parametrize("scenario_id", [p.stem for p in SCENARIOS_DIR.glob("*.yaml")])
def test_all_scenario_files_are_valid(scenario_id):
    load_scenario(scenario_id)


def test_template_is_not_listed_for_runs():
    assert "_template" not in list_scenarios()
    assert "main_v1" in list_scenarios()


def test_main_v1_covers_all_metrics():
    counts = summary(load_scenario("main_v1"))
    for check in ("probe", "immutable", "weird", "location"):
        assert counts[check] >= 4, check


def test_probe_k_is_computed():
    sc = load_scenario("main_v1")
    assert [t.probe.k for t in sc.turns if t.probe] == [2, 5, 18, 9, 19]


def make(turns: list[dict]) -> Scenario:
    return Scenario(id="x", world="zaginiona_korona", description="test", turns=turns)


@pytest.mark.parametrize("turns, message", [
    ([{"action": "a", "probe": {"fact": "kon"}}], "którego nikt wcześniej nie podał"),
    ([{"action": "a", "location": "kosmos"}], "nie ma w świecie"),
    ([{"action": "a", "immutable": {"fact": "bohater.monety", "attack": "direct"}}], "nie jest faktem niezmiennym"),
    ([{"action": "a", "location": {"group": "kuznia"}}], "tylko jedną wizytę"),
    ([{"action": "a", "plant": {"fact": "kon", "accept": ["x"]}},
      {"action": "b", "probe": {"fact": "kon", "k": 5}}], "naprawdę k=1"),
])
def test_validator_catches_mistakes(turns, message):
    with pytest.raises(ScenarioError, match=message):
        validate(make(turns), WORLD)


def test_question_attack_requires_accept():
    with pytest.raises(ValueError, match="wymaga listy accept"):
        make([{"action": "a", "immutable": {"fact": "miecz.materiał", "attack": "question"}}])
