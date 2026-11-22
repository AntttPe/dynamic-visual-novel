"""Hasło do gry, gdy strona jest wystawiona do internetu (np. przez Tailscale Funnel).

GAME_PASSWORD w .env włącza logowanie. Puste = brak logowania (gra lokalna, testy).
Po poprawnym haśle przeglądarka dostaje ciasteczko z podpisem HMAC hasła,
więc zmiana hasła w .env wylogowuje wszystkich.
"""

import asyncio
import hashlib
import hmac
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.config import settings

COOKIE = "dvn_session"
MAX_AGE = 30 * 24 * 3600  # 30 dni
LOGIN_PAGE = Path(__file__).parent / "static" / "login.html"
OPEN_PATHS = {"/login", "/logout"}


def session_token(password: str) -> str:
    return hmac.new(password.encode(), b"dvn-session-v1", hashlib.sha256).hexdigest()


def logged_in(request: Request) -> bool:
    cookie = request.cookies.get(COOKIE, "")
    return hmac.compare_digest(cookie, session_token(settings.game_password))


async def require_login(request: Request, call_next) -> Response:
    """Middleware: bez ciasteczka API zwraca 401, a strony przekierowują na /login."""
    if not settings.game_password or request.url.path in OPEN_PATHS or logged_in(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Zaloguj się"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def login_page(error: str = "", status: int = 200) -> HTMLResponse:
    html = LOGIN_PAGE.read_text(encoding="utf-8").replace("{{error}}", error)
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


async def login_form(request: Request) -> Response:
    if not settings.game_password or logged_in(request):
        return RedirectResponse("/", status_code=303)
    return login_page()


async def login_submit(request: Request) -> Response:
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    password = form.get("password", [""])[0]
    if not settings.game_password:
        return RedirectResponse("/", status_code=303)
    if not hmac.compare_digest(password.encode(), settings.game_password.encode()):
        await asyncio.sleep(1)  # spowalnia zgadywanie hasła
        return login_page('<p class="error">Złe hasło.</p>', status=401)
    resp = RedirectResponse("/", status_code=303)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(COOKIE, session_token(settings.game_password), max_age=MAX_AGE,
                    httponly=True, samesite="lax", secure=secure)
    return resp


async def logout(request: Request) -> Response:
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp
