import asyncio
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import llm
from app.config import settings
from app.core.engine import GameEngine
from app.core.world import WorldNotFound, list_worlds, load_world
from app.storage.db import Store

app = FastAPI(title="Dynamic Visual Novel")

# Wymienne w testach: fabryka klientów LLM i magazyn danych
app.state.llm_factory = lambda model, world: llm.make_client(model, world, settings)
app.state.store = None
GAMES: dict[str, GameEngine] = {}
LOCKS: dict[str, asyncio.Lock] = {}

SUGGESTED_MODELS = [
    "demo",
    "ollama_chat/llama3.1:8b",
    "ollama_chat/gemma4:e4b",
    "ollama_chat/gemma4:12b",
    "ollama_chat/qwen3.6:27b",
    "openai/strata-big",
    "openai/large-reasoning",
    "hosted_vllm/<nazwa-modelu>",
    "anthropic/claude-haiku-5-5",
]


def get_store(request: Request) -> Store:
    if request.app.state.store is None:
        request.app.state.store = Store(Path(settings.data_dir) / "dvn.sqlite")
    return request.app.state.store


class NewGame(BaseModel):
    world_id: str = "zaginiona_korona"
    model: str | None = None
    history: Literal["full", "window"] | None = None
    window: int | None = Field(default=None, ge=1, le=100)
    state_in_prompt: bool | None = None
    seed: int | None = None


class PlayerTurn(BaseModel):
    action: str = Field(min_length=1, max_length=500)


def game_view(game: GameEngine) -> dict:
    w = game.world
    return {
        "game_id": game.game_id,
        "config": game.config,
        "world": {
            "id": w.id, "title": w.title, "player": w.player, "goal": w.goal,
            "intro": w.intro, "start_location": w.start_location,
        },
        "location": game.location,
        "known_locations": game.known_locations,
        "state": [f.model_dump() for f in game.state.facts()],
        "turns": [t.model_dump() for t in game.turns],
    }


@app.get("/api/health")
async def health() -> dict:
    """Sprawdza, czy aplikacja działa i które providery LLM są dostępne."""
    return {
        "status": "ok",
        "narrator_model": settings.default_narrator_model,
        "providers": {
            "anthropic": bool(settings.anthropic_api_key),
            "openai": bool(settings.openai_api_key),
            "gemini": bool(settings.gemini_api_key),
            "ollama": await llm.ollama_available(settings.ollama_base_url),
        },
        "ollama_base_url": settings.ollama_base_url,
    }


@app.get("/api/config")
def config() -> dict:
    """Ustawienia domyślne dla nowej gry."""
    return {
        "defaults": {
            "model": settings.default_narrator_model,
            "history": settings.memory_history,
            "window": settings.memory_window,
            "state_in_prompt": settings.memory_state_in_prompt,
        },
        "suggested_models": SUGGESTED_MODELS,
        "worlds": [{"id": w.id, "title": w.title} for w in list_worlds()],
    }


@app.post("/api/games")
def new_game(req: NewGame, request: Request) -> dict:
    try:
        world = load_world(req.world_id)
    except WorldNotFound:
        raise HTTPException(404, f"Nie ma świata „{req.world_id}”") from None
    model = (req.model or settings.default_narrator_model).strip()
    game = GameEngine(
        world,
        request.app.state.llm_factory(model, world),
        history=req.history or settings.memory_history,
        window=req.window or settings.memory_window,
        state_in_prompt=settings.memory_state_in_prompt if req.state_in_prompt is None else req.state_in_prompt,
        temperature=settings.narrator_temperature,
        max_tokens=settings.narrator_max_tokens,
        json_retries=settings.narrator_json_retries,
        seed=req.seed,
        store=get_store(request),
    )
    GAMES[game.game_id] = game
    LOCKS[game.game_id] = asyncio.Lock()
    return game_view(game)


def _game(game_id: str) -> GameEngine:
    game = GAMES.get(game_id)
    if not game:
        raise HTTPException(404, "Nie ma takiej gry. Serwer mógł się zrestartować, zacznij nową grę.")
    return game


@app.get("/api/games/{game_id}")
def get_game(game_id: str) -> dict:
    return game_view(_game(game_id))


@app.post("/api/games/{game_id}/turns")
async def play_turn(game_id: str, req: PlayerTurn) -> dict:
    game = _game(game_id)
    async with LOCKS[game_id]:
        try:
            record = await game.step(req.action)
        except llm.LLMError as e:
            raise HTTPException(
                502, f"Model {game.llm.model} nie odpowiada. Sprawdź, czy działa "
                     f"(Ollama, tunel do GPU albo klucz API). Szczegóły: {e}",
            ) from e
    return {"turn": record.model_dump(), "location": game.location,
            "known_locations": game.known_locations,
            "state": [f.model_dump() for f in game.state.facts()]}


# UI: pliki statyczne serwowane pod "/" (montowane na końcu, żeby nie przykryć /api)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
