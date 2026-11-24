"""Silnik gry: jedna tura od akcji gracza do zapisu w bazie.

Ten sam silnik obsługuje grę w przeglądarce i (później) skryptowe eksperymenty.
"""

import json
import re
import uuid

from pydantic import ValidationError

from app.core.context import (
    build_messages,
    easy_template,
    easy_version,
    ending_prompt,
    ending_version,
    prompt_version,
)
from app.core.memory import make_memory
from app.core.schemas import (
    GameOutcome,
    HintNarratorResponse,
    NarratorResponse,
    PlayNarratorResponse,
    TurnRecord,
    voices_of,
)
from app.core.state import WorldState
from app.core.world import Fact, World
from app.llm.base import LLMClient
from app.storage.db import Store

NARRATOR_SCHEMA = NarratorResponse.model_json_schema()
PLAY_NARRATOR_SCHEMA = PlayNarratorResponse.model_json_schema()
HINT_NARRATOR_SCHEMA = HintNarratorResponse.model_json_schema()


class GameOver(Exception):
    """Gra już się skończyła (wygrana, przegrana albo koniec limitu tur)."""


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json(text: str) -> str:
    """Wycina obiekt JSON z odpowiedzi (modele czasem dodają ```json albo blok <think>)."""
    text = _THINK.sub("", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("w odpowiedzi nie ma obiektu JSON")
    return text[start:end + 1]


def normalize_location(location_id: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", location_id.strip().lower()).strip("_") or "unknown"


class GameEngine:
    def __init__(
        self,
        world: World,
        llm: LLMClient,
        *,
        history: str = "window",
        window: int = 8,
        state_in_prompt: bool = True,
        temperature: float = 0.7,
        max_tokens: int | None = 1200,
        json_retries: int = 2,
        seed: int | None = None,
        store: Store | None = None,
        mode: str = "play",
        game_id: str | None = None,
        create_run: bool = True,
        endings: bool = False,
        max_turns: int | None = None,
        difficulty: str = "normal",
    ):
        """endings: narrator ocenia wygraną i przegraną (gra w przeglądarce). Eksperymenty zostają przy False,
        więc ich prompt i schemat JSON się nie zmieniają. max_turns: limit tur, po nim gra jest przegrana.
        difficulty: "normal" albo "easy" (narrator ułatwia wygraną, tylko razem z endings)."""
        if difficulty not in ("normal", "easy"):
            raise ValueError(f"Nieznany poziom trudności: {difficulty}")
        self.game_id = game_id or uuid.uuid4().hex[:12]
        self.world = world
        self.llm = llm
        self.memory = make_memory(history, window)
        self.state = WorldState(world.facts)
        self.location = world.start_location
        self.known_locations = {loc.id: loc.name for loc in world.locations}
        self.turns: list[TurnRecord] = []
        self._restored = 0  # tury odtworzone z bazy przy wznowieniu
        self.store = store
        self.endings = endings
        self.max_turns = max_turns
        self.outcome = GameOutcome()
        self.difficulty = difficulty if endings else "normal"
        self._ending = ending_prompt(world, max_turns) if endings else None
        if self._ending and self.difficulty == "easy":
            self._ending = f"{self._ending.strip()}\n\n{easy_template().strip()}"
        version = prompt_version()
        if endings:
            version += f"+end{ending_version()}"
        if self.difficulty == "easy":
            version += f"+easy{easy_version()}"
        self.config = {
            "mode": mode,
            "world_id": world.id,
            "model": llm.model,
            "history": history,
            "memory_window": window,
            "state_in_prompt": state_in_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_retries": json_retries,
            "seed": seed,
            "prompt_version": version,
        }
        if getattr(llm, "reasoning_effort", None):  # gra w przeglądarce z ograniczonym myśleniem modelu
            self.config["reasoning_effort"] = llm.reasoning_effort
        if endings:
            self.config["max_turns"] = max_turns
            self.config["difficulty"] = self.difficulty
        if store and create_run:
            store.create_run(self.game_id, self.config)

    def restore(self, rows: list[dict]) -> None:
        """Odtwarza pamięć, stan świata i lokację z zapisanych tur (wznowienie przerwanego eksperymentu)."""
        for row in rows:
            if row["error"] is None:
                parsed = NarratorResponse.model_validate_json(extract_json(row["raw_output"]))
                self.memory.record(self._remembered(row["player_action"], json.loads(row["prompt"])), parsed)
                self.known_locations.setdefault(row["location"], (row["scene_description"] or "")[:60])
            self.location = row["location"]
            self.state = WorldState([Fact(**f) for f in json.loads(row["state_after"])])
        self._restored = len(rows)

    def _remembered(self, action: str, prompt: list[dict]) -> str:
        """Co pamięć zapisuje jako wiadomość gracza: samą akcję albo całą wysłaną wiadomość (full_cached)."""
        return prompt[-1]["content"] if getattr(self.memory, "records_sent_message", False) else action

    @property
    def finished(self) -> bool:
        return self.outcome.status != "ongoing"

    async def step(self, player_action: str) -> TurnRecord:
        """Rozgrywa jedną turę. LLMError (model niedostępny) przechodzi wyżej, tura nie jest zapisana."""
        action = player_action.strip()
        if not action:
            raise ValueError("Pusta akcja gracza")
        if self.finished:
            raise GameOver(self.outcome.reason)
        cfg = self.config
        t = self._restored + len(self.turns) + 1
        turn_info = None
        if self.endings:
            turn_info = f"To jest tura {t} z {self.max_turns}." if self.max_turns else f"To jest tura {t}."
        prompt = build_messages(
            self.world, self.state, self.memory, action,
            current_location=self.location,
            known_locations=self.known_locations,
            state_in_prompt=cfg["state_in_prompt"],
            ending=self._ending,
            turn_info=turn_info,
        )
        if self.difficulty == "easy":
            response_model, schema = HintNarratorResponse, HINT_NARRATOR_SCHEMA
        elif self.endings:
            response_model, schema = PlayNarratorResponse, PLAY_NARRATOR_SCHEMA
        else:
            response_model, schema = NarratorResponse, NARRATOR_SCHEMA
        conversation = list(prompt)
        parsed, raw, error = None, "", None
        tokens_in = tokens_out = tokens_cached = 0
        latency_ms = 0.0
        ttft_ms = first_answer_ms = None
        attempts = 0
        for _ in range(cfg["json_retries"] + 1):
            result = await self.llm.complete(
                conversation,
                json_schema=schema,
                temperature=cfg["temperature"],
                seed=cfg["seed"],
                max_tokens=cfg["max_tokens"],
            )
            attempts += 1
            if attempts == 1:  # ponowienie ma dłuższy prompt, więc liczy się czas pierwszej próby
                ttft_ms, first_answer_ms = result.ttft_ms, result.first_answer_ms
            tokens_in += result.tokens_in
            tokens_out += result.tokens_out
            tokens_cached += result.tokens_cached
            latency_ms += result.latency_ms
            raw = result.text
            try:
                parsed = response_model.model_validate_json(extract_json(raw))
                error = None
                break
            except (ValidationError, ValueError) as e:
                error = f"Niepoprawny JSON: {str(e).splitlines()[0]}"
                conversation += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Twoja odpowiedź nie była poprawnym JSON-em zgodnym z "
                     "formatem. Odpowiedz ponownie wyłącznie poprawnym obiektem JSON."},
                ]

        accepted, rejected = [], []
        if parsed:
            accepted, rejected = self.state.apply(parsed.state_updates)
            self.location = normalize_location(parsed.scene.location_id)
            self.known_locations.setdefault(self.location, parsed.scene.description[:60])
            self.memory.record(self._remembered(action, prompt), parsed)

        outcome = None
        if self.endings:
            outcome = parsed.outcome if parsed else GameOutcome()
            if outcome.status == "ongoing" and self.max_turns and t >= self.max_turns:
                outcome = GameOutcome(status="lost", reason=f"Skończył się limit tur ({self.max_turns}), "
                                      "a cel nie został osiągnięty.")
            self.outcome = outcome

        record = TurnRecord(
            t=t,
            outcome=outcome,
            hint=(parsed.hint.strip() or None) if isinstance(parsed, HintNarratorResponse) else None,
            voices=voices_of(parsed),
            player_action=action,
            response=parsed,
            raw_output=raw,
            json_ok_first_try=parsed is not None and attempts == 1,
            retries=attempts - 1,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            first_answer_ms=first_answer_ms,
            prompt=prompt,
            accepted_updates=accepted,
            rejected_updates=rejected,
            location=self.location,
            state_after=self.state.facts(),
            error=error if parsed is None else None,
        )
        self.turns.append(record)
        if self.store:
            self.store.save_turn(self.game_id, record)
        return record
