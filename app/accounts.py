"""Konta: hasła graczy, sekret serwera i szyfrowanie kluczy API w bazie.

Wszystko z biblioteki standardowej Pythona:
- hasła: scrypt z losową solą,
- klucze API graczy: szyfr strumieniowy z HMAC-SHA256 (licznik jak w trybie CTR)
  i drugi HMAC jako podpis, który wykrywa zmienione albo uszkodzone dane.

Sekret serwera to SECRET_KEY z .env. Gdy go nie ma, serwer tworzy losowy w data/secret.key
(katalog data nie trafia do repo). Zmiana albo utrata sekretu wylogowuje wszystkich
i sprawia, że zapisanych kluczy API nie da się odczytać (trzeba je wpisać od nowa).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
from functools import lru_cache
from pathlib import Path

from app.config import settings

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32, **_SCRYPT)
    return hmac.compare_digest(test.hex(), digest)


@lru_cache(maxsize=4)
def _secret(env_value: str, data_dir: str) -> bytes:
    if env_value:
        return env_value.encode()
    path = Path(data_dir) / "secret.key"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()


def server_secret() -> bytes:
    return _secret(settings.secret_key, settings.data_dir)


def _key(purpose: bytes) -> bytes:
    return hmac.new(server_secret(), purpose, hashlib.sha256).digest()


def sign(message: str) -> str:
    return hmac.new(_key(b"dvn-session-v2"), message.encode(), hashlib.sha256).hexdigest()


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt(data: dict) -> str:
    """Słownik (np. klucze API) jako zaszyfrowany tekst do zapisu w bazie."""
    plain = json.dumps(data, ensure_ascii=False).encode()
    nonce = os.urandom(16)
    cipher = bytes(a ^ b for a, b in zip(plain, _stream(_key(b"dvn-enc-v1"), nonce, len(plain)), strict=True))
    tag = hmac.new(_key(b"dvn-mac-v1"), nonce + cipher, hashlib.sha256).digest()
    return "v1:" + base64.urlsafe_b64encode(nonce + cipher + tag).decode()


class DecryptError(ValueError):
    pass


def decrypt(token: str) -> dict:
    if not token.startswith("v1:"):
        raise DecryptError("Nieznany format zaszyfrowanych danych")
    raw = base64.urlsafe_b64decode(token[3:].encode())
    nonce, cipher, tag = raw[:16], raw[16:-32], raw[-32:]
    expected = hmac.new(_key(b"dvn-mac-v1"), nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise DecryptError("Nie da się odczytać kluczy API: zmienił się SECRET_KEY albo dane są uszkodzone")
    plain = bytes(a ^ b for a, b in zip(cipher, _stream(_key(b"dvn-enc-v1"), nonce, len(cipher)), strict=True))
    return json.loads(plain)
