"""Warstwa modeli językowych."""

import httpx

from app.config import Settings
from app.core.world import World
from app.llm.base import LLMClient, LLMError, LLMResult
from app.llm.demo import DemoLLM
from app.llm.litellm_client import LiteLLMClient

__all__ = ["LLMClient", "LLMError", "LLMResult", "make_client", "ollama_available"]


def make_client(model: str, world: World, settings: Settings,
                api_base: str | None = None, api_key: str | None = None,
                reasoning_effort: str | None = None) -> LLMClient:
    """Tworzy klienta dla modelu w formacie LiteLLM albo tryb demo ("demo").

    api_base i api_key to własne API gracza z okna „Nowa gra”. Puste = ustawienia z .env.
    """
    if model == "demo":
        return DemoLLM(world)
    return LiteLLMClient(model, settings, api_base=api_base, api_key=api_key, reasoning_effort=reasoning_effort)


async def ollama_available(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            return (await client.get(base_url)).status_code == 200
    except httpx.HTTPError:
        return False
