"""Logowanie: konto administratora z .env i konta graczy z bazy (tabela users).

ADMIN_PASSWORD w .env włącza logowanie (stare GAME_PASSWORD działa jako hasło administratora).
Puste = brak logowania: każdy ma prawa administratora (gra lokalna, testy).

Administrator: wszystko jak w zwykłej grze plus panel /admin z kontami graczy.
Gracz: widzi tylko swoją przygotowaną grę (i jej komiks), nie zakłada nowych gier
i nie widzi cudzych. Uprawnienia sprawdza middleware, więc obejmują też API.

Ciasteczko sesji: login, data ważności i podpis HMAC sekretem serwera. Podpis zależy też
od hasła konta, więc zmiana hasła (albo usunięcie konta) wylogowuje tę osobę.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import accounts
from app.config import settings

COOKIE = "dvn_session"
MAX_AGE = 30 * 24 * 3600  # 30 dni
LOGIN_PAGE = Path(__file__).parent / "static" / "login.html"
OPEN_PATHS = {"/login", "/logout"}
ADMIN_PATHS = ("/api/admin", "/admin", "/docs", "/redoc", "/openapi.json")
GAME_PATH = re.compile(r"^/api/games/([^/]+)")

# Gdy logowanie jest wyłączone, każdy jest administratorem
LOCAL_ADMIN = {"login": "local", "role": "admin", "game_id": None}


def accounts_on() -> bool:
    return bool(settings.admin_pass)


def _store(request: Request):
    from app.main import get_store  # bez cyklu importów: main importuje auth

    return get_store(request)


def _password_tag(login: str, request: Request) -> str | None:
    """Część podpisu zależna od hasła konta. None = nie ma takiego konta."""
    if login == settings.admin_login:
        return hashlib.sha256(settings.admin_pass.encode()).hexdigest()
    user = _store(request).user(login)
    return user["password_hash"] if user else None


def session_token(login: str, request: Request, now: float | None = None) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"u": login, "exp": int((now or time.time()) + MAX_AGE)}).encode()).decode()
    return f"{payload}.{accounts.sign(payload + '|' + (_password_tag(login, request) or ''))}"


def current_user(request: Request) -> dict | None:
    """Zalogowane konto z ciasteczka: login, rola, gra gracza. None = brak ważnej sesji."""
    if not accounts_on():
        return LOCAL_ADMIN
    token = request.cookies.get(COOKIE, "")
    payload, _, signature = token.partition(".")
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        login, exp = str(data["u"]), int(data["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    if exp < time.time():
        return None
    tag = _password_tag(login, request)
    if tag is None or not hmac.compare_digest(signature, accounts.sign(payload + "|" + tag)):
        return None
    if login == settings.admin_login:
        return {"login": login, "role": "admin", "game_id": None}
    user = _store(request).user(login)
    return {"login": login, "role": "player", "game_id": user["game_id"]}


def _forbidden(request: Request) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "To konto nie ma do tego dostępu"}, status_code=403)
    return RedirectResponse("/", status_code=303)


async def require_login(request: Request, call_next) -> Response:
    """Middleware: bez sesji API zwraca 401, a strony przekierowują na /login. Gracz ma ograniczony dostęp."""
    path = request.url.path
    if path in OPEN_PATHS:
        return await call_next(request)
    user = current_user(request)
    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Zaloguj się"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    request.state.user = user
    if user["role"] == "player":
        if path.startswith(ADMIN_PATHS):
            return _forbidden(request)
        if path == "/api/games" and request.method != "GET":
            return _forbidden(request)
        match = GAME_PATH.match(path)
        if match and match.group(1) != user["game_id"]:
            return JSONResponse({"detail": "Nie ma takiej gry."}, status_code=404)
    return await call_next(request)


def login_page(error: str = "", status: int = 200, login: str = "") -> HTMLResponse:
    html = (LOGIN_PAGE.read_text(encoding="utf-8").replace("{{error}}", error)
            .replace("{{login}}", login.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")))
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


async def login_form(request: Request) -> Response:
    if not accounts_on() or current_user(request):
        return RedirectResponse("/", status_code=303)
    return login_page()


def _valid(login: str, password: str, request: Request) -> bool:
    if login == settings.admin_login:
        return hmac.compare_digest(password.encode(), settings.admin_pass.encode())
    user = _store(request).user(login)
    return bool(user) and accounts.check_password(password, user["password_hash"])


async def login_submit(request: Request) -> Response:
    if not accounts_on():
        return RedirectResponse("/", status_code=303)
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    login = form.get("login", [""])[0].strip()
    password = form.get("password", [""])[0]
    if not login or not _valid(login, password, request):
        await asyncio.sleep(1)  # spowalnia zgadywanie hasła
        return login_page('<p class="error">Zły login albo hasło.</p>', status=401, login=login)
    resp = RedirectResponse("/", status_code=303)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(COOKIE, session_token(login, request), max_age=MAX_AGE,
                    httponly=True, samesite="lax", secure=secure)
    return resp


async def logout(request: Request) -> Response:
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp
