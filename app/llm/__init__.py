"""Warstwa modeli językowych."""

import httpx

from app.config import Settings
from app.core.world import World
from app.llm.base import LLMClient, LLMError, LLMResult
from app.llm.demo import DemoLLM
from app.llm.litellm_client import LiteLLMClient

__all__ = ["LLMClient", "LLMError", "LLMResult", "make_client", "ollama_available"]


def make_client(model: str, world: World, settings: Settings) -> LLMClient:
    """Tworzy klienta dla modelu w formacie LiteLLM albo tryb demo ("demo")."""
    if model == "demo":
        return DemoLLM(world)
    return LiteLLMClient(model, settings)


async def ollama_available(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            return (await client.get(base_url)).status_code == 200
    except httpx.HTTPError:
        return False
