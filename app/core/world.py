"""Definicja świata gry: fakty startowe, lokacje, cel. Wczytywana z app/worlds/*.yaml."""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

WORLDS_DIR = Path(__file__).resolve().parent.parent / "worlds"
_WORLD_ID = re.compile(r"^[a-z0-9_]+$")


class Fact(BaseModel):
    entity: str
    attribute: str
    value: str
    immutable: bool = False


class Location(BaseModel):
    id: str
    name: str
    description: str
    # Rdzenie słów, po których rozpoznajemy lokację w tekście gracza (tryb demo, później scenariusze)
    aliases: list[str] = Field(default_factory=list)


class World(BaseModel):
    id: str
    title: str
    player: str
    setting: str
    goal: str
    rules: list[str] = Field(default_factory=list)
    start_location: str
    intro: str
    locations: list[Location] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)

    def location(self, location_id: str) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)


class WorldNotFound(Exception):
    pass


def load_world(world_id: str) -> World:
    path = WORLDS_DIR / f"{world_id}.yaml"
    if not _WORLD_ID.match(world_id) or not path.exists():
        raise WorldNotFound(world_id)
    return World.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def list_worlds() -> list[World]:
    return [load_world(p.stem) for p in sorted(WORLDS_DIR.glob("*.yaml"))]
