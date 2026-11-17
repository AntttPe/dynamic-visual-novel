"""Świat z pomysłu gracza: wybrany model narratora zamienia opis gracza w pełny świat startowy.

Wytyczne są w app/prompts/world_builder.md, a wzorem jest świat „Zaginiona korona”.
Wynik przechodzi przez tę samą walidację co światy z YAML, więc gra nie wie, skąd świat pochodzi.
"""

import hashlib
import json
import re
from pathlib import Path
from string import Template

from pydantic import BaseModel, Field, ValidationError

from app.core.engine import extract_json, normalize_location
from app.core.world import Fact, Location, World, load_world
from app.llm.base import LLMClient

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "world_builder.md"
EXAMPLE_WORLD = "zaginiona_korona"
CUSTOM_WORLD = "custom"  # world_id w oknie „Nowa gra” oznaczający świat z pomysłu gracza


class LocationDraft(BaseModel):
    id: str
    name: str
    description: str


class WorldDraft(BaseModel):
    """To, co model ma zwrócić. Pola jak w World, bez id i aliasów."""

    title: str = Field(min_length=1)
    player: str = Field(min_length=1)
    setting: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    win_condition: str = Field(min_length=1)
    lose_condition: str = Field(min_length=1)
    rules: list[str] = Field(default_factory=list)
    visual_style: str = Field(min_length=1)
    start_location: str
    intro: str = Field(min_length=1)
    locations: list[LocationDraft] = Field(min_length=1)
    facts: list[Fact] = Field(default_factory=list)


DRAFT_SCHEMA = WorldDraft.model_json_schema()


class WorldBuildError(Exception):
    """Model nie zwrócił poprawnego świata po wszystkich próbach."""

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


class BuiltWorld(BaseModel):
    world: World
    idea: str
    prompt: list[dict]
    raw_output: str
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0


def example_json() -> str:
    w = load_world(EXAMPLE_WORLD)
    draft = w.model_dump(exclude={"id"})
    for loc in draft["locations"]:
        loc.pop("aliases", None)
    return json.dumps(draft, ensure_ascii=False, indent=1)


def prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_messages(idea: str) -> list[dict]:
    system = Template(prompt_template()).safe_substitute(example=example_json())
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Pomysł gracza na świat:\n{idea.strip()}"},
    ]


def world_id_for(idea: str, raw: str) -> str:
    return f"custom_{hashlib.sha256((idea + raw).encode()).hexdigest()[:8]}"


def to_world(draft: WorldDraft, world_id: str) -> World:
    """Porządkuje szkic: identyfikatory lokacji w snake_case, bez powtórzeń, start wśród lokacji."""
    locations: list[Location] = []
    for loc in draft.locations:
        loc_id = normalize_location(loc.id)
        if all(existing.id != loc_id for existing in locations):
            # Aliasy z nazwy (tryb demo rozpoznaje po nich lokację w akcji gracza)
            words = [w[:max(4, len(w) - 2)] for w in re.findall(r"\w{4,}", loc.name.lower())]
            locations.append(Location(id=loc_id, name=loc.name.strip(), description=loc.description.strip(),
                                      aliases=words[:3]))
    start = normalize_location(draft.start_location)
    if all(loc.id != start for loc in locations):
        start = locations[0].id
    facts = [Fact(entity=f.entity.strip().lower(), attribute=f.attribute.strip().lower(), value=f.value.strip(),
                  immutable=f.immutable) for f in draft.facts if f.entity.strip() and f.attribute.strip()]
    return World(
        id=world_id, title=draft.title.strip(), player=draft.player.strip(), setting=draft.setting.strip(),
        goal=draft.goal.strip(), win_condition=draft.win_condition.strip(),
        lose_condition=draft.lose_condition.strip(), rules=[r.strip() for r in draft.rules if r.strip()],
        visual_style=draft.visual_style.strip(), start_location=start,
        intro=draft.intro.strip(), locations=locations, facts=facts,
    )


def demo_world(idea: str) -> BuiltWorld:
    """Tryb demo nie ma modelu: wzorcowy świat z pomysłem gracza w opisie, żeby pokazać przepływ."""
    w = load_world(EXAMPLE_WORLD)
    world = w.model_copy(update={
        "id": world_id_for(idea, "demo"),
        "title": "Własny świat (demo)",
        "setting": f"{w.setting} (Tryb demo nie tworzy świata. Pomysł gracza: {idea.strip()})",
    })
    return BuiltWorld(world=world, idea=idea, prompt=build_messages(idea), raw_output="")


async def build_world(llm: LLMClient, idea: str, *, temperature: float = 0.7, seed: int | None = None,
                      max_tokens: int | None = None, retries: int = 2) -> BuiltWorld:
    """Zamienia pomysł gracza w świat. LLMError (model niedostępny) przechodzi wyżej."""
    prompt = build_messages(idea)
    conversation = list(prompt)
    raw, error = "", ""
    tokens_in = tokens_out = 0
    latency_ms = 0.0
    for attempt in range(retries + 1):
        result = await llm.complete(conversation, json_schema=DRAFT_SCHEMA, temperature=temperature, seed=seed,
                                    max_tokens=max_tokens)
        tokens_in += result.tokens_in
        tokens_out += result.tokens_out
        latency_ms += result.latency_ms
        raw = result.text
        try:
            draft = WorldDraft.model_validate_json(extract_json(raw))
        except (ValidationError, ValueError) as e:
            error = str(e).splitlines()[0]
            conversation += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Twoja odpowiedź nie była poprawnym JSON-em zgodnym z formatem "
                 f"wzoru ({error}). Odpowiedz ponownie wyłącznie poprawnym obiektem JSON."},
            ]
            continue
        return BuiltWorld(world=to_world(draft, world_id_for(idea, raw)), idea=idea, prompt=prompt,
                          raw_output=raw, retries=attempt, tokens_in=tokens_in, tokens_out=tokens_out,
                          latency_ms=latency_ms)
    raise WorldBuildError(f"Model nie zwrócił poprawnego świata: {error}", raw)
