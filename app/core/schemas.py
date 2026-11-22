"""Struktury danych tury: co zwraca narrator i co zapisujemy do bazy."""

from typing import Literal

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


class GameOutcome(BaseModel):
    """Stan gry po turze. Tylko gra w przeglądarce, eksperymenty go nie używają."""

    status: Literal["ongoing", "won", "lost"] = "ongoing"
    reason: str = Field(default="", description="Krótko, dlaczego gra się skończyła. Puste, gdy trwa.")


class VoicedLine(DialogueLine):
    """Kwestia w grze: do tego płeć mówiącego, żeby lektor czytał ją kobiecym albo męskim głosem."""

    gender: Literal["female", "male"] | None = Field(default=None, description="Płeć postaci, która mówi.")


class PlayNarratorResponse(NarratorResponse):
    """Odpowiedź narratora w grze: to samo co w eksperymentach plus wynik gry i płeć mówiących."""

    dialogue: list[VoicedLine] = Field(default_factory=list)
    outcome: GameOutcome = Field(default_factory=GameOutcome)


class HintNarratorResponse(PlayNarratorResponse):
    """Gra z podpowiedziami: do tego jedna wskazówka, co zrobić dalej, pokazywana obok sceny."""

    hint: str = Field(default="", description="Jedno krótkie zdanie: następny krok gracza w stronę wygranej.")


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
    tokens_cached: int = 0
    latency_ms: float
    ttft_ms: float | None = None  # pierwsza próba, tylko przy strumieniowaniu
    first_answer_ms: float | None = None
    prompt: list[dict]
    accepted_updates: list[StateUpdate] = Field(default_factory=list)
    rejected_updates: list[RejectedUpdate] = Field(default_factory=list)
    location: str
    state_after: list[Fact] = Field(default_factory=list)
    error: str | None = None
    outcome: GameOutcome | None = None  # tylko gra z wykrywaniem końca (None w eksperymentach)
    hint: str | None = None  # tylko gra z podpowiedziami (None w eksperymentach i bez podpowiedzi)
    voices: dict[str, str] | None = None  # płeć mówiących dla lektora, tylko gra w przeglądarce


def voices_of(parsed: NarratorResponse | None) -> dict[str, str] | None:
    """Płeć mówiących z odpowiedzi narratora w grze: {"Borwin": "male"}. None w eksperymentach."""
    if not isinstance(parsed, PlayNarratorResponse):
        return None
    return {line.speaker: line.gender for line in parsed.dialogue if line.gender}
