"""Wspólny interfejs dla wszystkich modeli językowych.

Gra i eksperymenty korzystają tylko z tego interfejsu, więc zmiana providera
(Ollama, vLLM, API) nie wymaga zmian w reszcie kodu.
"""

from typing import Protocol

from pydantic import BaseModel


class LLMResult(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0  # część tokens_in wzięta z cache serwera (0, gdy serwer tego nie zgłasza)
    latency_ms: float = 0.0


class LLMError(Exception):
    """Model niedostępny albo zwrócił błąd (sieć, klucz API, nieznany model)."""


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult: ...
