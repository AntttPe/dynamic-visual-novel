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
        self._stream = settings.narrator_stream

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
        if self._stream:
            # Serwer wysyła zużycie tokenów w ostatnim fragmencie strumienia
            extra["stream"] = True
            extra["stream_options"] = {"include_usage": True}
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
            if self._stream:
                return await self._read_stream(resp, start)
        except Exception as e:  # LiteLLM zamienia błędy providerów na własne wyjątki
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000
        usage = getattr(resp, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        return LLMResult(
            text=resp.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            tokens_cached=getattr(details, "cached_tokens", 0) or 0,
            latency_ms=latency_ms,
        )

    async def _read_stream(self, resp, start: float) -> LLMResult:
        """Składa odpowiedź ze strumienia i mierzy czas do pierwszego tokenu myślenia i odpowiedzi."""
        text, usage = "", None
        ttft = first_answer = first_chunk = None
        async for chunk in resp:
            usage = getattr(chunk, "usage", None) or usage
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            content = getattr(delta, "content", None)
            now = (time.perf_counter() - start) * 1000
            if first_chunk is None:
                first_chunk = now
            if ttft is None and (reasoning or content):
                ttft = now
            if content:
                text += content
                if first_answer is None and answer_started(text):
                    first_answer = now
        details = getattr(usage, "prompt_tokens_details", None)
        return LLMResult(
            text=text,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            tokens_cached=getattr(details, "cached_tokens", 0) or 0,
            latency_ms=(time.perf_counter() - start) * 1000,
            # Bez tekstu (np. odpowiedź ucięta po 1 tokenie) liczy się pierwszy fragment w ogóle
            ttft_ms=ttft if ttft is not None else first_chunk,
            first_answer_ms=first_answer,
        )


def answer_started(text: str) -> bool:
    """Czy w tekście zaczęła się odpowiedź. Myślenie wysłane w treści jako <think>...</think> się nie liczy."""
    s = text.lstrip()
    if not s:
        return False
    if s.startswith("<think>") or "<think>".startswith(s):
        end = s.find("</think>")
        return end != -1 and s[end + len("</think>"):].strip() != ""
    return True
