"""Struktury danych tury: co zwraca narrator i co zapisujemy do bazy."""

from pydantic import BaseModel, Field

from app.core.world import Fact


class DialogueLine(BaseModel):
    speaker: str = Field(description="Kto mówi, np. Borwin")
    text: str


class Scene(BaseModel):
    location_id: str = Field(
        description="Identyfikator miejsca, w którym gracz jest po tej turze: małe litery, "
        "po angielsku, snake_case. To samo miejsce ma zawsze ten sam identyfikator."
    )
    description: str = Field(
        description="Wygląd miejsca do wygenerowania tła, maks. 30 słów, bez postaci i akcji."
    )


class StateUpdate(BaseModel):
    entity: str
    attribute: str
    value: str


class NarratorResponse(BaseModel):
    narration: str = Field(description="Opis skutków działania gracza w 2. osobie, 2 do 5 zdań.")
    dialogue: list[DialogueLine] = Field(default_factory=list)
    scene: Scene
    state_updates: list[StateUpdate] = Field(
        default_factory=list, description="Tylko faktyczne zmiany stanu świata w tej turze."
    )
    characters_present: list[str] = Field(default_factory=list)


class RejectedUpdate(BaseModel):
    update: StateUpdate
    reason: str


class TurnRecord(BaseModel):
    """Wszystko, co wiemy o jednej turze. Surowe dane do metryk."""

    t: int
    player_action: str
    response: NarratorResponse | None
    raw_output: str
    json_ok_first_try: bool
    retries: int
    tokens_in: int
    tokens_out: int
    latency_ms: float
    prompt: list[dict]
    accepted_updates: list[StateUpdate] = Field(default_factory=list)
    rejected_updates: list[RejectedUpdate] = Field(default_factory=list)
    location: str
    state_after: list[Fact] = Field(default_factory=list)
    error: str | None = None
