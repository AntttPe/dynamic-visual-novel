"""Panel administratora: konta graczy z przygotowaną grą.

Administrator zakłada konto (login i hasło) i od razu ustawia graczowi scenariusz, model tekstowy
i grafikę. Serwer w tle buduje świat i zamawia pierwsze obrazy, więc gracz po zalogowaniu
nie czeka kilku minut na pierwszą turę. Klucze API konta są w bazie zaszyfrowane (app/accounts.py)
i nigdy nie wracają w odpowiedziach serwera.
"""

import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import accounts
from app.config import settings

router = APIRouter()
STATIC = Path(__file__).parent / "static"
TASKS: dict[str, asyncio.Task] = {}  # login -> przygotowywana gra (referencja, żeby zadanie nie zniknęło)


class PlayerSetup(BaseModel):
    """Ustawienia gry gracza. Puste klucze = klucze z .env."""

    # Scenariusz
    world_id: str = "custom"
    world_idea: str | None = Field(default=None, max_length=2000)
    max_turns: int | None = Field(default=None, ge=1, le=500)
    difficulty: Literal["normal", "easy"] = "normal"
    history: Literal["full", "window", "full_cached"] | None = None
    # Model tekstowy (format LiteLLM) i opcjonalnie własne API
    model: str = Field(default="", max_length=200)
    text_api_base: str = Field(default="", max_length=500)
    text_api_key: str = Field(default="", max_length=500)
    # Grafika: server = serwer obrazów z .env, dvn = inny serwer serve.py, litellm = API obrazów, off = bez obrazów
    image_kind: Literal["server", "dvn", "litellm", "off"] = "server"
    image_model: str | None = None  # generator serwera projektu (server, dvn)
    image_url: str = Field(default="", max_length=500)
    image_lm_model: str = Field(default="", max_length=200)
    image_api_key: str = Field(default="", max_length=500)
    image_size: str = Field(default="1536x1024", pattern=r"^\d{2,5}x\d{2,5}$")


SECRET_FIELDS = ("text_api_key", "image_api_key")


class NewPlayer(PlayerSetup):
    login: str = Field(pattern=r"^[A-Za-z0-9_.-]{2,40}$")
    password: str = Field(min_length=6, max_length=200)


class NewPassword(BaseModel):
    password: str = Field(min_length=6, max_length=200)


def _require_admin(request: Request) -> None:
    from app.auth import LOCAL_ADMIN

    if getattr(request.state, "user", LOCAL_ADMIN)["role"] != "admin":
        raise HTTPException(403, "To konto nie ma do tego dostępu")


def setup_of(user: dict) -> PlayerSetup:
    """Pełne ustawienia konta, razem z odszyfrowanymi kluczami API."""
    data = json.loads(user["setup"])
    if user["secrets"]:
        data.update(accounts.decrypt(user["secrets"]))
    return PlayerSetup.model_validate(data)


def new_game_request(setup: PlayerSetup):
    from app.main import ImageApi, NewGame, TextApi

    image_api = None
    if setup.image_kind in ("dvn", "litellm"):
        image_api = ImageApi(kind=setup.image_kind, url=setup.image_url, model=setup.image_lm_model,
                             api_key=setup.image_api_key, size=setup.image_size)
    text_api = TextApi(api_base=setup.text_api_base, api_key=setup.text_api_key) \
        if setup.text_api_base or setup.text_api_key else None
    return NewGame(world_id=setup.world_id, world_idea=setup.world_idea, max_turns=setup.max_turns,
                   difficulty=setup.difficulty, history=setup.history, model=setup.model or None,
                   image_model=setup.image_model, text_api=text_api, image_api=image_api)


def apply_player_setup(game, user: dict, llm_factory, images) -> None:
    """Po restarcie serwera gra gracza dostaje z powrotem swój model, API i grafikę z ustawień konta."""
    from app.main import make_image_client

    try:
        setup = setup_of(user)
    except accounts.DecryptError:
        return  # klucze nie do odczytania: gra działa na ustawieniach z .env
    text_api = {k: v for k, v in {"api_base": setup.text_api_base, "api_key": setup.text_api_key}.items() if v}
    if text_api:
        game.llm = llm_factory(game.config["model"], game.world, **text_api)
        game.custom_text_api = True
    req = new_game_request(setup)
    if setup.image_kind == "off":
        images.disabled.add(game.game_id)
    elif req.image_api:
        images.clients[game.game_id] = make_image_client(req.image_api)
        if req.image_api.kind == "litellm":
            images.models[game.game_id] = req.image_api.model.strip()
    if setup.image_kind in ("server", "dvn") and setup.image_model:
        images.models[game.game_id] = setup.image_model


PREPARE_ATTEMPTS = 3  # wspólny serwer modelu bywa zajęty kilka minut, a gracz i tak nie czeka przy ekranie


async def prepare_game(login: str, request: Request) -> None:
    """Buduje grę konta w tle. Stan w bazie: pending, ready albo failed (z opisem błędu).

    Gdy model nie odpowiada albo zwraca zły świat (HTTP 502), próbuje jeszcze raz, do PREPARE_ATTEMPTS razy.
    """
    from app.main import create_game, get_store

    store = get_store(request)
    store.update_user(login, status="pending", error=None)
    for attempt in range(1, PREPARE_ATTEMPTS + 1):
        try:
            user = store.user(login)
            if not user:
                return  # konto usunięte w trakcie
            setup = setup_of(user)
            game = await create_game(new_game_request(setup), request, images_off=setup.image_kind == "off")
        except HTTPException as e:
            if e.status_code == 502 and attempt < PREPARE_ATTEMPTS and store.user(login):
                store.update_user(login, error=f"Próba {attempt} z {PREPARE_ATTEMPTS} nieudana, próbuję jeszcze raz. "
                                               f"{e.detail}")
                continue
            store.update_user(login, status="failed", error=str(e.detail))
        except Exception as e:  # noqa: BLE001  błąd modelu albo sieci nie może zostawić konta w „pending”
            store.update_user(login, status="failed", error=f"{type(e).__name__}: {e}")
        else:
            if store.user(login):  # konto mogło zostać usunięte w trakcie
                store.update_user(login, game_id=game.game_id, status="ready", error=None)
        return


def preparing(login: str) -> bool:
    task = TASKS.get(login)
    return bool(task) and not task.done()


def start_preparing(login: str, request: Request) -> None:
    """Wymaga działającej pętli asyncio (wywołanie z endpointu async)."""
    task = asyncio.create_task(prepare_game(login, request))
    TASKS[login] = task
    task.add_done_callback(lambda t: TASKS.pop(login, None) if TASKS.get(login) is t else None)


def checked(store, user: dict) -> dict:
    """Konto „pending” bez działającego zadania (np. po restarcie serwera) oznaczamy jako błąd do ponowienia."""
    if user["status"] == "pending" and not preparing(user["login"]):
        store.update_user(user["login"], status="failed",
                          error="Przygotowanie gry zostało przerwane (np. restart serwera). Kliknij „Ponów”.")
        user = store.user(user["login"])
    return user


def user_view(user: dict) -> dict:
    """Konto do panelu administratora. Bez hasła i bez kluczy API (tylko informacja, że są)."""
    setup = json.loads(user["setup"])
    return {
        "login": user["login"], "created_at": user["created_at"], "status": user["status"],
        "error": user["error"], "game_id": user["game_id"], "setup": setup,
        "has_text_key": bool(user["secrets"]) and "text_api_key" in _secret_names(user),
        "has_image_key": bool(user["secrets"]) and "image_api_key" in _secret_names(user),
    }


def _secret_names(user: dict) -> set[str]:
    try:
        return set(accounts.decrypt(user["secrets"])) if user["secrets"] else set()
    except accounts.DecryptError:
        return set()


def _validate(setup: PlayerSetup) -> None:
    from app.core.world import WorldNotFound, load_world
    from app.core.world_builder import CUSTOM_WORLD
    from app.main import IMAGE_MODELS

    if setup.world_id == CUSTOM_WORLD:
        if len((setup.world_idea or "").strip()) < 3:
            raise HTTPException(422, "Opisz scenariusz gracza (kilka słów wystarczy)")
    else:
        try:
            load_world(setup.world_id)
        except WorldNotFound:
            raise HTTPException(422, f"Nie ma świata „{setup.world_id}”") from None
    if setup.image_kind in ("server", "dvn") and setup.image_model \
            and setup.image_model not in {m["id"] for m in IMAGE_MODELS}:
        raise HTTPException(422, f"Nie ma generatora obrazów „{setup.image_model}”")
    if setup.image_kind == "dvn" and not setup.image_url.strip():
        raise HTTPException(422, "Podaj adres serwera obrazów")
    if setup.image_kind == "litellm" and not setup.image_lm_model.strip():
        raise HTTPException(422, "Podaj model obrazów w formacie LiteLLM, np. openai/gpt-image-1")


# ---------- API ----------

@router.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-cache"})


@router.get("/api/me")
def me(request: Request) -> dict:
    """Kto jest zalogowany. Gracz dostaje też stan swojej gry (pending, ready, failed)."""
    from app.auth import LOCAL_ADMIN, accounts_on
    from app.main import get_store

    user = getattr(request.state, "user", LOCAL_ADMIN)
    result = {"login": user["login"], "role": user["role"], "accounts": accounts_on()}
    if user["role"] == "player":
        store = get_store(request)
        row = store.user(user["login"])
        row = checked(store, row) if row else {}
        result.update(game_id=row.get("game_id"), status=row.get("status"), error=row.get("error"))
    return result


@router.get("/api/admin/users")
def list_users(request: Request) -> list[dict]:
    _require_admin(request)
    from app.main import get_store

    store = get_store(request)
    return [user_view(checked(store, u)) for u in store.users()]


@router.post("/api/admin/users", status_code=201)
async def add_user(req: NewPlayer, request: Request) -> dict:
    """Nowe konto gracza. Gra przygotowuje się w tle, stan widać w GET /api/admin/users."""
    _require_admin(request)
    from app.main import get_store

    if req.login == settings.admin_login:
        raise HTTPException(422, "Ten login ma administrator")
    store = get_store(request)
    if store.user(req.login):
        raise HTTPException(409, f"Konto „{req.login}” już istnieje")
    setup = PlayerSetup.model_validate(req.model_dump(exclude={"login", "password"}))
    _validate(setup)
    public = setup.model_dump(exclude=set(SECRET_FIELDS))
    secret = {k: getattr(setup, k).strip() for k in SECRET_FIELDS if getattr(setup, k).strip()}
    store.add_user(req.login, accounts.hash_password(req.password), public,
                   accounts.encrypt(secret) if secret else None)
    start_preparing(req.login, request)
    return user_view(store.user(req.login))


@router.post("/api/admin/users/{login}/game")
async def new_player_game(login: str, request: Request) -> dict:
    """Nowa gra dla gracza z tymi samymi ustawieniami (także „Ponów” po błędzie). Stara gra zostaje w bazie."""
    _require_admin(request)
    from app.main import get_store

    store = get_store(request)
    user = store.user(login)
    if not user:
        raise HTTPException(404, "Nie ma takiego konta")
    if preparing(login):
        raise HTTPException(409, "Gra tego gracza jeszcze się przygotowuje")
    start_preparing(login, request)
    return user_view(store.user(login))


@router.post("/api/admin/users/{login}/password")
def change_password(login: str, req: NewPassword, request: Request) -> dict:
    _require_admin(request)
    from app.main import get_store

    store = get_store(request)
    if not store.user(login):
        raise HTTPException(404, "Nie ma takiego konta")
    store.update_user(login, password_hash=accounts.hash_password(req.password))
    return user_view(store.user(login))


@router.delete("/api/admin/users/{login}")
def delete_user(login: str, request: Request) -> dict:
    """Usuwa konto. Rozegrane gry zostają w bazie (do metryk) i widać je w zapisanych grach."""
    _require_admin(request)
    from app.main import get_store

    store = get_store(request)
    if not store.user(login):
        raise HTTPException(404, "Nie ma takiego konta")
    store.delete_user(login)
    return {"deleted": login}
