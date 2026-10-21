"""Scenariusze badawcze: z góry napisane sekwencje akcji gracza z oczekiwaniami.

Scenariusz to instrument pomiarowy. Każda tura może mieć kilka sprawdzeń
(plant, probe, location, immutable, weird), a każde sprawdzenie należy do jednej metryki.
Pliki: app/eval/scenarios/*.yaml. Opis pól: app/eval/scenarios/_template.yaml.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.world import World, load_world

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


class Plant(BaseModel):
    """Gracz podaje fakt do zapamiętania (metryka 1)."""

    fact: str
    accept: list[str] = Field(min_length=1)


class Probe(BaseModel):
    """Pytanie kontrolne o wcześniej podany fakt (metryka 1). k liczy loader."""

    fact: str
    k: int | None = None


class LocationGroup(BaseModel):
    """Nowe miejsce spoza świata: identyfikator dowolny, ale ten sam przy każdej wizycie."""

    group: str


class Immutable(BaseModel):
    """Atak na fakt niezmienny ze świata (metryka 2)."""

    fact: str  # "encja.atrybut", np. "miecz.materiał"
    attack: Literal["question", "direct", "gaslight"]
    # Dla "question": słowa, z których jedno musi paść w odpowiedzi
    accept: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _question_needs_accept(self):
        if self.attack == "question" and not self.accept:
            raise ValueError("attack: question wymaga listy accept")
        return self


WeirdCategory = Literal["magic", "missing_item", "resources", "absurd", "out_of_role", "self_harm"]


class Weird(BaseModel):
    """Nietypowa komenda gracza (metryka 3). criterion czyta sędzia LLM."""

    category: WeirdCategory
    criterion: str


class Turn(BaseModel):
    action: str = Field(min_length=1, max_length=500)
    note: str = ""
    plant: Plant | None = None
    probe: Probe | None = None
    location: str | LocationGroup | None = None
    immutable: Immutable | None = None
    weird: Weird | None = None

    def checks(self) -> list[str]:
        return [name for name in ("plant", "probe", "location", "immutable", "weird")
                if getattr(self, name) is not None]


class Scenario(BaseModel):
    id: str
    version: int = 1
    world: str
    description: str
    turns: list[Turn] = Field(min_length=1)


class ScenarioError(ValueError):
    pass


def _fact_key(ref: str) -> tuple[str, str]:
    entity, _, attribute = ref.partition(".")
    return entity.strip().lower(), attribute.strip().lower()


def validate(scenario: Scenario, world: World) -> None:
    """Sprawdza spójność scenariusza ze światem i wylicza k dla pytań kontrolnych."""
    errors = []
    planted: dict[str, int] = {}
    immutable = {_fact_key(f"{f.entity}.{f.attribute}") for f in world.facts if f.immutable}
    location_ids = {loc.id for loc in world.locations}

    for i, turn in enumerate(scenario.turns, start=1):
        where = f"tura {i}"
        if turn.plant:
            if turn.plant.fact in planted:
                errors.append(f"{where}: fakt „{turn.plant.fact}” podany drugi raz")
            planted[turn.plant.fact] = i
        if turn.probe:
            if turn.probe.fact not in planted:
                errors.append(f"{where}: pytanie o „{turn.probe.fact}”, którego nikt wcześniej nie podał")
            else:
                k = i - planted[turn.probe.fact]
                if turn.probe.k is not None and turn.probe.k != k:
                    errors.append(f"{where}: k={turn.probe.k}, a naprawdę k={k}")
                turn.probe.k = k
        if isinstance(turn.location, str) and turn.location not in location_ids:
            errors.append(f"{where}: lokacji „{turn.location}” nie ma w świecie (użyj group: dla nowych)")
        if turn.immutable and _fact_key(turn.immutable.fact) not in immutable:
            errors.append(f"{where}: „{turn.immutable.fact}” nie jest faktem niezmiennym świata")

    groups = [t.location.group for t in scenario.turns if isinstance(t.location, LocationGroup)]
    for g in set(groups):
        if groups.count(g) < 2:
            errors.append(f"grupa lokacji „{g}” ma tylko jedną wizytę, nie ma czego porównać")
    if errors:
        raise ScenarioError(f"Scenariusz {scenario.id}:\n- " + "\n- ".join(errors))


def load_scenario(scenario_id: str) -> Scenario:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise ScenarioError(f"Nie ma scenariusza {scenario_id}")
    scenario = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if scenario.id != scenario_id:
        raise ScenarioError(f"id „{scenario.id}” w pliku {path.name} musi być takie jak nazwa pliku")
    validate(scenario, load_world(scenario.world))
    return scenario


def list_scenarios() -> list[str]:
    """Scenariusze do uruchamiania. Pliki zaczynające się od "_" (szablon) są pomijane."""
    return [p.stem for p in sorted(SCENARIOS_DIR.glob("*.yaml")) if not p.stem.startswith("_")]


def summary(scenario: Scenario) -> dict[str, int]:
    """Ile sprawdzeń ma każda metryka. Przydatne przy projektowaniu scenariusza."""
    counts = {"turns": len(scenario.turns)}
    for turn in scenario.turns:
        for check in turn.checks():
            counts[check] = counts.get(check, 0) + 1
    return counts
