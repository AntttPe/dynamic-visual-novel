"""Klient do lokalnych modeli przez Ollamę (HTTP API)."""

import httpx

from app.config import settings


async def ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            return (await client.get(settings.ollama_base_url)).status_code == 200
    except httpx.HTTPError:
        return False


async def ollama_chat(messages: list[dict], model: str | None = None) -> str:
    """Wysyła historię rozmowy do Ollamy i zwraca odpowiedź modelu.

    messages: [{"role": "system" | "user" | "assistant", "content": "..."}]
    """
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={"model": model or settings.ollama_model, "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
