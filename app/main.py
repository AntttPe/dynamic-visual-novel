import asyncio
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import llm
from app.config import settings
from app.core.engine import GameEngine
from app.core.world import WorldNotFound, list_worlds, load_world
from app.images import (
    MAX_PORTRAITS,
    BackgroundImages,
    HttpImageClient,
    portrait_prompt,
    present_characters,
    scene_prompt,
)
from app.storage.db import Store

app = FastAPI(title="Dynamic Visual Novel")

# Wymienne w testach: fabryka klientów LLM i magazyn danych
app.state.llm_factory = lambda model, world: llm.make_client(model, world, settings)
app.state.store = None
app.state.images = None
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


IMAGE_MODELS = [
    {"id": "flux2-klein-4b", "label": "FLUX.2 klein 4B (szybki)"},
    {"id": "qwen-image-21-turbo", "label": "Qwen-Image-2.1-Turbo (dokładniejszy, wolny)"},
    {"id": "sdxl-ip", "label": "SDXL + IP-Adapter"},
    {"id": "sdxl-ip-face", "label": "SDXL + IP-Adapter Face"},
]


def get_store(request: Request) -> Store:
    if request.app.state.store is None:
        request.app.state.store = Store(Path(settings.data_dir) / "dvn.sqlite")
    return request.app.state.store


def get_images(request: Request) -> BackgroundImages:
    if request.app.state.images is None:
        url = settings.image_server_url
        client = HttpImageClient(url, settings.image_timeout_s) if url else None
        request.app.state.images = BackgroundImages(
            client, Path(settings.data_dir) / "images", get_store(request), settings.image_style,
        )
    return request.app.state.images


def request_background(request: Request, game: GameEngine, location: str, description: str, t: int) -> None:
    """Zamawia tło. Opis lokacji ze świata ma pierwszeństwo, bo jest stały, opis narratora zmienia się co turę."""
    known = game.world.location(location)
    get_images(request).request(game.game_id, location, known.description if known else description,
                                game.config["seed"], t)


def request_portrait(request: Request, game: GameEngine, name: str, entity: str | None, t: int) -> None:
    prompt = portrait_prompt(settings.image_portrait_style, name, game.state.facts(), entity)
    get_images(request).request_portrait(game.game_id, name, prompt, game.config["seed"], t)


class NewGame(BaseModel):
    world_id: str = "zaginiona_korona"
    model: str | None = None
    history: Literal["full", "window", "full_cached"] | None = None
    window: int | None = Field(default=None, ge=1, le=100)
    state_in_prompt: bool | None = None
    seed: int | None = None
    image_model: str | None = None


class PlayerTurn(BaseModel):
    action: str = Field(min_length=1, max_length=500)


def game_view(game: GameEngine, images: BackgroundImages) -> dict:
    w = game.world
    return {
        "game_id": game.game_id,
        "config": game.config,
        "image_model": images.models.get(game.game_id) if images.client else None,
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
            "openai": bool(settings.openai_api_key or settings.narrator_api_key),
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
            "image_model": settings.image_model,
        },
        "suggested_models": SUGGESTED_MODELS,
        "image_models": IMAGE_MODELS if settings.image_server_url else [],
        "worlds": [{"id": w.id, "title": w.title} for w in list_worlds()],
    }


@app.post("/api/games")
async def new_game(req: NewGame, request: Request) -> dict:
    try:
        world = load_world(req.world_id)
    except WorldNotFound:
        raise HTTPException(404, f"Nie ma świata „{req.world_id}”") from None
    image_model = req.image_model or settings.image_model
    if image_model not in {m["id"] for m in IMAGE_MODELS}:
        raise HTTPException(422, f"Nie ma generatora obrazów „{image_model}”")
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
    get_images(request).models[game.game_id] = image_model
    request_background(request, game, game.location, "", 0)
    request_portrait(request, game, game.world.player, "bohater", 0)
    return game_view(game, get_images(request))


def _game(game_id: str) -> GameEngine:
    game = GAMES.get(game_id)
    if not game:
        raise HTTPException(404, "Nie ma takiej gry. Serwer mógł się zrestartować, zacznij nową grę.")
    return game


@app.get("/api/games/{game_id}")
def get_game(game_id: str, request: Request) -> dict:
    return game_view(_game(game_id), get_images(request))


@app.post("/api/games/{game_id}/turns")
async def play_turn(game_id: str, req: PlayerTurn, request: Request) -> dict:
    game = _game(game_id)
    async with LOCKS[game_id]:
        try:
            record = await game.step(req.action)
        except llm.LLMError as e:
            raise HTTPException(
                502, f"Model {game.llm.model} nie odpowiada. Sprawdź, czy działa "
                     f"(Ollama, tunel do GPU albo klucz API). Szczegóły: {e}",
            ) from e
    if record.response:
        r = record.response
        request_background(request, game, game.location, r.scene.description, record.t)
        images = get_images(request)
        visible, hidden = images.cast(game.game_id, game.world.start_location).update(
            game.location, present_characters(game.world.player, r.characters_present), req.action)
        others = visible[:MAX_PORTRAITS - 1]
        for name in others:
            request_portrait(request, game, name, None, record.t)
        known = game.world.location(game.location)
        prompt = scene_prompt(settings.image_scene_style, known.description if known else r.scene.description,
                              game.world.player, game.state.facts(), visible, req.action, r.narration, hidden)
        images.request_scene(game.game_id, record.t, game.location, prompt, game.config["seed"],
                             [game.world.player, *others])
    return {"turn": record.model_dump(), "location": game.location,
            "known_locations": game.known_locations,
            "state": [f.model_dump() for f in game.state.facts()]}


@app.get("/api/games/{game_id}/image")
def image_status(game_id: str, location: str, request: Request) -> dict:
    """Stan tła lokacji: off, none, pending, failed albo ready (z adresem pliku)."""
    _game(game_id)
    return get_images(request).status(game_id, location)


@app.get("/api/games/{game_id}/image/file")
def image_file(game_id: str, location: str, request: Request) -> FileResponse:
    _game(game_id)
    path = get_images(request).path(game_id, location)
    if path is None:
        raise HTTPException(404, "Tego tła jeszcze nie ma")
    return FileResponse(path, media_type="image/png")


@app.get("/api/games/{game_id}/scene")
def scene_status(game_id: str, t: int, request: Request) -> dict:
    """Stan obrazu tury: off, none, pending, failed albo ready (z adresem pliku)."""
    _game(game_id)
    return get_images(request).scene_status(game_id, t)


@app.get("/api/games/{game_id}/scene/file")
def scene_file(game_id: str, t: int, request: Request) -> FileResponse:
    _game(game_id)
    path = get_images(request).scene_path(game_id, t)
    if path is None:
        raise HTTPException(404, "Tego obrazu jeszcze nie ma")
    return FileResponse(path, media_type="image/png")


class RevalidatedStatic(StaticFiles):
    """Przeglądarka pyta przy każdym wejściu, czy plik się zmienił, więc nie zostaje przy starym app.js."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# UI: pliki statyczne serwowane pod "/" (montowane na końcu, żeby nie przykryć /api)
app.mount("/", RevalidatedStatic(directory=Path(__file__).parent / "static", html=True), name="static")
