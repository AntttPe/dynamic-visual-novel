"""Klient LLM oparty o LiteLLM: jeden kod dla Ollamy, vLLM i modeli przez API."""

import time

import litellm

from app.config import Settings
from app.llm.base import LLMError, LLMResult

# Parametry, których provider nie obsługuje (np. seed w Anthropic), są pomijane zamiast błędu.
litellm.drop_params = True
litellm.suppress_debug_info = True

_API_KEYS = {
    "anthropic/": "anthropic_api_key",
    "openai/": "openai_api_key",
    "gemini/": "gemini_api_key",
}


def resolve_api_base(model: str, settings: Settings) -> str | None:
    if model.startswith(("ollama/", "ollama_chat/")):
        return settings.ollama_base_url
    if model.startswith(("hosted_vllm/", "openai/")):
        return settings.narrator_api_base or None
    return None


def resolve_api_key(model: str, settings: Settings) -> str | None:
    if settings.narrator_api_key and model.startswith(("hosted_vllm/", "openai/")):
        return settings.narrator_api_key
    for prefix, field in _API_KEYS.items():
        if model.startswith(prefix):
            return getattr(settings, field) or None
    return None


class LiteLLMClient:
    def __init__(self, model: str, settings: Settings):
        self.model = model
        self._api_base = resolve_api_base(model, settings)
        self._api_key = resolve_api_key(model, settings)
        self._timeout = settings.narrator_timeout_s

    async def complete(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        extra = {}
        if json_schema is not None:
            # Ollama zamienia to na parametr "format" i wymusza zgodność ze schematem
            extra["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "narrator_response", "schema": json_schema},
            }
        start = time.perf_counter()
        try:
            resp = await litellm.acompletion(
                model=self.model,
                messages=messages,
                api_base=self._api_base,
                api_key=self._api_key,
                temperature=temperature,
                seed=seed,
                max_tokens=max_tokens,
                timeout=self._timeout,
                **extra,
            )
        except Exception as e:  # LiteLLM zamienia błędy providerów na własne wyjątki
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000
        usage = getattr(resp, "usage", None)
        return LLMResult(
            text=resp.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
        )
