import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import admin, auth, llm
from app.config import settings
from app.core.engine import GameEngine, GameOver
from app.core.saved import load_game, saved_world
from app.core.world import (
    COVER_TYPES,
    WorldNotFound,
    cover_path,
    list_worlds,
    load_world,
)
from app.core.world_builder import (
    CUSTOM_WORLD,
    EXAMPLE_WORLD,
    BuiltWorld,
    WorldBuildError,
    build_world,
    demo_world,
)
from app.images import (
    MAX_PORTRAITS,
    BackgroundImages,
    HttpImageClient,
    LiteLLMImageClient,
    Looks,
    legacy_look,
    mentioned,
    portrait_prompt,
    present_characters,
    scene_prompt,
    styled,
    visual_text,
)
from app.storage.db import Store

app = FastAPI(title="Dynamic Visual Novel")

# Logowanie hasłem z GAME_PASSWORD (puste = gra bez hasła), patrz app/auth.py
app.middleware("http")(auth.require_login)
app.add_api_route("/login", auth.login_form, methods=["GET"], include_in_schema=False)
app.add_api_route("/login", auth.login_submit, methods=["POST"], include_in_schema=False)
app.add_api_route("/logout", auth.logout, methods=["GET", "POST"], include_in_schema=False)
# Panel administratora: konta graczy z przygotowanymi grami, patrz app/admin.py
app.include_router(admin.router)

# Wymienne w testach: fabryka klientów LLM i magazyn danych
app.state.llm_factory = lambda model, world, **api: llm.make_client(
    model, world, settings, reasoning_effort=settings.play_reasoning_effort, **api)
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


def place_look(game: GameEngine, location: str, narrator_look: str = "", description: str = "") -> str:
    """Wygląd miejsca do obrazu. Opis ze świata ma pierwszeństwo, bo jest stały. Po angielsku, a po polsku
    tylko w starych grach i światach bez pola look."""
    known = game.world.location(location)
    if known:
        return known.look or narrator_look or known.description
    return narrator_look or description


def request_background(request: Request, game: GameEngine, location: str, description: str, t: int,
                       look: str = "") -> None:
    get_images(request).request(game.game_id, location, place_look(game, location, look, description),
                                game.config["seed"], t, game.world.visual_style)


def looks_of(request: Request, game: GameEngine) -> Looks:
    """Wygląd postaci gry po angielsku: ze świata i z new_characters we wszystkich turach (także po restarcie)."""
    images = get_images(request)
    looks = images.looks.get(game.game_id)
    if looks is None:
        looks = images.looks[game.game_id] = Looks.of_world(game.world)
        for turn in game.turns:
            for character in getattr(turn.response, "new_characters", None) or []:
                looks.add(character.name, character.look)
    return looks


def character_look(game: GameEngine, looks: Looks, name: str, hero: bool = False) -> str:
    """Wygląd postaci po angielsku, a w starych grach wygląd z faktów świata."""
    if hero:
        return looks.find(Looks.HERO) or looks.find(game.world.player.split(",")[0]) or             legacy_look(game.state.facts(), Looks.HERO)
    return looks.find(name) or legacy_look(game.state.facts(), name)


def request_portrait(request: Request, game: GameEngine, name: str, t: int, hero: bool = False) -> None:
    looks = looks_of(request, game)
    look = character_look(game, looks, name, hero)
    prompt = portrait_prompt(styled(settings.image_portrait_style, game.world.visual_style), look)
    get_images(request).request_portrait(game.game_id, name if hero else looks.canonical(name), prompt,
                                         game.config["seed"], t)


class TextApi(BaseModel):
    """Własne API modelu tekstowego z okna „Nowa gra”. Puste pola = ustawienia z .env."""

    api_base: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=500)


class ImageApi(BaseModel):
    """Własne API obrazów z okna „Nowa gra”.

    dvn: serwer obrazów projektu (bench/images/consistency/serve.py) pod innym adresem niż w .env,
    litellm: dowolne API obrazów obsługiwane przez LiteLLM, np. openai/gpt-image-1.
    """

    kind: Literal["dvn", "litellm"]
    url: str = Field(default="", max_length=500)  # dvn: adres serwera, litellm: api_base (opcjonalnie)
    model: str = Field(default="", max_length=200)  # litellm: model w formacie LiteLLM
    api_key: str = Field(default="", max_length=500)
    size: str = Field(default="1536x1024", pattern=r"^\d{2,5}x\d{2,5}$")


def make_image_client(api: ImageApi):
    if api.kind == "dvn":
        if not api.url.strip():
            raise HTTPException(422, "Podaj adres serwera obrazów")
        return HttpImageClient(api.url.strip(), settings.image_timeout_s)
    if not api.model.strip():
        raise HTTPException(422, "Podaj model obrazów w formacie LiteLLM, np. openai/gpt-image-1")
    return LiteLLMImageClient(api.model.strip(), api.url.strip(), api.api_key.strip(), settings.image_timeout_s,
                              api.size)


class NewGame(BaseModel):
    world_id: str = "zaginiona_korona"
    model: str | None = None
    history: Literal["full", "window", "full_cached"] | None = None
    window: int | None = Field(default=None, ge=1, le=100)
    state_in_prompt: bool | None = None
    seed: int | None = None
    image_model: str | None = None
    # Własne API gracza. Klucze nie trafiają do bazy ani do odpowiedzi serwera.
    text_api: TextApi | None = None
    image_api: ImageApi | None = None
    # Pomysł gracza na świat, gdy world_id == "custom". Model narratora zamienia go w pełny świat.
    world_idea: str | None = Field(default=None, max_length=2000)
    # Limit tur. Po nim gra kończy się przegraną, jeśli cel nie został osiągnięty. None = bez limitu.
    max_turns: int | None = Field(default=None, ge=1, le=500)
    # "easy": narrator ułatwia wygraną (app/prompts/narrator_easy.md). Tylko gra w przeglądarce.
    difficulty: Literal["normal", "easy"] = "normal"


class PlayerTurn(BaseModel):
    action: str = Field(min_length=1, max_length=500)


def game_view(game: GameEngine, images: BackgroundImages) -> dict:
    w = game.world
    return {
        "game_id": game.game_id,
        "config": game.config,
        "image_model": images.models.get(game.game_id) if images.client_for(game.game_id) else None,
        "custom_text_api": getattr(game, "custom_text_api", False),
        "custom_image_api": game.game_id in images.clients,
        "world": {
            "id": w.id, "title": w.title, "player": w.player, "goal": w.goal,
            "intro": w.intro, "start_location": w.start_location, "setting": w.setting,
            "rules": w.rules, "custom": w.id.startswith(f"{CUSTOM_WORLD}_"),
            "win_condition": w.win_condition, "lose_condition": w.lose_condition,
        },
        "max_turns": game.max_turns,
        "difficulty": game.difficulty,
        "outcome": game.outcome.model_dump(),
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
        "image_models": IMAGE_MODELS,
        "image_server": bool(settings.image_server_url),
        "worlds": [{"id": w.id, "title": w.title, "player": w.player, "goal": w.goal, "setting": w.setting,
                    "cover": f"/api/worlds/{w.id}/cover" if cover_path(w.id) else None} for w in list_worlds()],
    }


@app.get("/api/worlds/{world_id}/cover")
def world_cover(world_id: str) -> FileResponse:
    """Okładka świata do menu (plik obok YAML świata)."""
    path = cover_path(world_id)
    if path is None:
        raise HTTPException(404, "Ten świat nie ma okładki")
    return FileResponse(path, media_type=COVER_TYPES[path.suffix])


async def make_world(req: NewGame, request: Request, model: str, text_api: dict) -> BuiltWorld:
    """Świat z pomysłu gracza, stworzony przez ten sam model, który potem prowadzi grę."""
    idea = (req.world_idea or "").strip()
    if len(idea) < 3:
        raise HTTPException(422, "Opisz pomysł na świat (kilka słów wystarczy)")
    if model == "demo":
        return demo_world(idea)
    client = request.app.state.llm_factory(model, load_world(EXAMPLE_WORLD), **text_api)
    try:
        return await build_world(client, idea, temperature=settings.narrator_temperature, seed=req.seed,
                                 max_tokens=max(settings.narrator_max_tokens, 4000),
                                 retries=settings.narrator_json_retries)
    except llm.LLMError as e:
        raise HTTPException(502, f"Model {model} nie odpowiada. Szczegóły: {e}") from e
    except WorldBuildError as e:
        raise HTTPException(502, f"{e} Spróbuj jeszcze raz albo użyj większego modelu.") from e


@app.post("/api/games")
async def new_game(req: NewGame, request: Request) -> dict:
    return game_view(await create_game(req, request), get_images(request))


async def create_game(req: NewGame, request: Request, images_off: bool = False) -> GameEngine:
    """Nowa gra: świat (z YAML albo z pomysłu gracza), silnik tury i zamówienie pierwszych obrazów."""
    image_model = req.image_model or settings.image_model
    if image_model not in {m["id"] for m in IMAGE_MODELS}:
        raise HTTPException(422, f"Nie ma generatora obrazów „{image_model}”")
    image_client = make_image_client(req.image_api) if req.image_api else None
    if req.image_api and req.image_api.kind == "litellm":
        image_model = req.image_api.model.strip()
    model = (req.model or settings.default_narrator_model).strip()
    text_api = {k: v.strip() for k, v in (req.text_api.model_dump() if req.text_api else {}).items() if v.strip()}
    built = None
    if req.world_id == CUSTOM_WORLD:
        built = await make_world(req, request, model, text_api)
        world = built.world
    else:
        try:
            world = load_world(req.world_id)
        except WorldNotFound:
            raise HTTPException(404, f"Nie ma świata „{req.world_id}”") from None
    game = GameEngine(
        world,
        request.app.state.llm_factory(model, world, **text_api),
        history=req.history or settings.memory_history,
        window=req.window or settings.memory_window,
        state_in_prompt=settings.memory_state_in_prompt if req.state_in_prompt is None else req.state_in_prompt,
        temperature=settings.narrator_temperature,
        max_tokens=settings.narrator_max_tokens,
        json_retries=settings.narrator_json_retries,
        seed=req.seed,
        store=get_store(request),
        endings=True,
        max_turns=req.max_turns,
        difficulty=req.difficulty,
    )
    game.custom_text_api = bool(text_api)
    if built:
        get_store(request).save_world(game.game_id, model, built)
    GAMES[game.game_id] = game
    LOCKS[game.game_id] = asyncio.Lock()
    images = get_images(request)
    images.models[game.game_id] = image_model
    if image_client:
        images.clients[game.game_id] = image_client
    if images_off:
        images.disabled.add(game.game_id)
    request_background(request, game, game.location, "", 0)
    request_portrait(request, game, game.world.player, 0, hero=True)
    # Postacie z intro rysujemy od razu, żeby pierwsza scena miała gotowe portrety
    for character in [c for c in game.world.characters if mentioned(c.name, game.world.intro)][:MAX_PORTRAITS - 1]:
        request_portrait(request, game, character.name, 0)
    return game


def _game(game_id: str) -> GameEngine:
    """Gra z pamięci, a po restarcie serwera odtworzona z bazy (razem z gotowymi obrazami)."""
    game = GAMES.get(game_id)
    if game:
        return game
    store = app.state.store or Store(Path(settings.data_dir) / "dvn.sqlite")
    app.state.store = store
    try:
        game = load_game(store, game_id, app.state.llm_factory)
    except Exception:  # noqa: BLE001  zepsuty zapis nie może wywrócić serwera
        game = None
    if not game:
        raise HTTPException(404, "Nie ma takiej gry ani jej zapisu w bazie.")
    GAMES[game_id] = game
    LOCKS[game_id] = asyncio.Lock()
    images = app.state.images
    if images is None:  # pierwsze zapytanie po restarcie: ten sam obiekt, który zrobiłoby get_images
        url = settings.image_server_url
        images = app.state.images = BackgroundImages(
            HttpImageClient(url, settings.image_timeout_s) if url else None,
            Path(settings.data_dir) / "images", store, settings.image_style,
        )
    images.restore(game_id, store.images(game_id))
    user = store.user_by_game(game_id)
    if user:  # gra z konta gracza: jej model i API obrazów z ustawień konta (klucze z bazy)
        admin.apply_player_setup(game, user, app.state.llm_factory, images)
    return game


def _thumb(store: Store, game_id: str) -> Path | None:
    """Ostatni gotowy obraz sceny gry, a bez scen tło lokacji: miniatura na liście zapisanych gier."""
    ready = [r for r in store.images(game_id) if r["status"] == "ready" and r["path"] and Path(r["path"]).is_file()]
    for kind in ("scene", "background"):
        found = [r for r in ready if r["kind"] == kind]
        if found:
            return Path(found[-1]["path"])
    return None


@app.get("/api/games")
def saved_games(request: Request) -> list[dict]:
    """Rozegrane gry z bazy (najnowsze najpierw), do przeglądania w menu. Gry bez tur są pomijane."""
    store = get_store(request)
    user = getattr(request.state, "user", auth.LOCAL_ADMIN)
    result = []
    for run in store.play_runs():
        if not run["turns"]:
            continue
        if user["role"] == "player" and run["run_id"] != user["game_id"]:
            continue
        config = json.loads(run["config"])
        title = json.loads(run["world"])["title"] if run["world"] else None
        if title is None:
            world = saved_world(store, run)
            title = world.title if world else run["world_id"]
        outcome = json.loads(run["outcome"])["status"] if run["outcome"] else None
        result.append({
            "game_id": run["run_id"], "created_at": run["created_at"], "title": title, "model": run["model"],
            "turns": run["turns"], "outcome": outcome, "hints": config.get("difficulty") == "easy",
            "custom": run["world"] is not None,
            "thumb": f"/api/games/{run['run_id']}/thumb" if _thumb(store, run["run_id"]) else None,
        })
    return result


@app.get("/api/games/{game_id}/thumb")
def game_thumb(game_id: str, request: Request) -> FileResponse:
    path = _thumb(get_store(request), game_id)
    if path is None:
        raise HTTPException(404, "Ta gra nie ma obrazów")
    return FileResponse(path, media_type="image/png")


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
        except GameOver:
            raise HTTPException(409, "Ta gra już się skończyła. Zacznij nową grę.") from None
    if record.response:
        r = record.response
        narrator_look = getattr(r.scene, "look", "")
        request_background(request, game, game.location, r.scene.description, record.t, narrator_look)
        images = get_images(request)
        looks = looks_of(request, game)
        for character in getattr(r, "new_characters", None) or []:
            looks.add(character.name, character.look)
        present = [looks.canonical(name) for name in present_characters(game.world.player, r.characters_present)]
        visible, hidden = images.cast(game.game_id, game.world.start_location).update(
            game.location, present_characters(game.world.player, present), req.action)
        others = visible[:MAX_PORTRAITS - 1]
        for name in others:
            request_portrait(request, game, name, record.t)
        people = [character_look(game, looks, game.world.player, hero=True),
                  *(character_look(game, looks, name) for name in others)]
        picture = getattr(r, "picture", "").strip() or visual_text(req.action, r.narration, hidden)
        prompt = scene_prompt(styled(settings.image_scene_style, game.world.visual_style),
                              place_look(game, game.location, narrator_look, r.scene.description), people, picture)
        images.request_scene(game.game_id, record.t, game.location, prompt, game.config["seed"],
                             [game.world.player, *others])
    return {"turn": record.model_dump(), "location": game.location,
            "known_locations": game.known_locations,
            "state": [f.model_dump() for f in game.state.facts()],
            "outcome": game.outcome.model_dump()}


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


def _ready_url(status: dict) -> str | None:
    return status.get("url") if status.get("status") == "ready" else None


@app.get("/api/games/{game_id}/comic")
def comic(game_id: str, request: Request) -> dict:
    """Komiks z rozgrywki: dla każdej tury obraz (scena, a gdy jej nie ma, tło lokacji) i opis tego, co się stało."""
    game = _game(game_id)
    images = get_images(request)

    def place_image(location: str) -> str | None:
        return _ready_url(images.status(game_id, location))

    panels = [{
        "t": 0, "action": None, "text": game.world.intro, "dialogue": [],
        "location": game.known_locations.get(game.world.start_location, game.world.start_location),
        "image": place_image(game.world.start_location),
    }]
    for turn in game.turns:
        if turn.response is None:  # tura z błędem narratora nic nie zmieniła w historii
            continue
        panels.append({
            "t": turn.t, "action": turn.player_action, "text": turn.response.narration,
            "dialogue": [d.model_dump(include={"speaker", "text"}) for d in turn.response.dialogue],
            "location": game.known_locations.get(turn.location, turn.location),
            "image": _ready_url(images.scene_status(game_id, turn.t)) or place_image(turn.location),
        })
    built = get_store(request).world(game_id)  # świat z pomysłu gracza: jego prompt trafia do komiksu
    return {
        "game_id": game_id, "title": game.world.title, "player": game.world.player, "goal": game.world.goal,
        "world_idea": built["idea"] if built else None,
        "outcome": game.outcome.model_dump(), "panels": panels,
    }


class RevalidatedStatic(StaticFiles):
    """Przeglądarka pyta przy każdym wejściu, czy plik się zmienił, więc nie zostaje przy starym app.js."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# UI: pliki statyczne serwowane pod "/" (montowane na końcu, żeby nie przykryć /api)
app.mount("/", RevalidatedStatic(directory=Path(__file__).parent / "static", html=True), name="static")
