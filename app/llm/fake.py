"""Model na niby do testów: zwraca przygotowane odpowiedzi, bez sieci i GPU."""

from app.llm.base import LLMError, LLMResult


class FakeLLM:
    def __init__(self, responses: list[str | Exception] | None = None, model: str = "fake/narrator"):
        self.model = model
        self.responses = list(responses or [])
        self.calls: list[list[dict]] = []

    async def complete(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        self.calls.append(messages)
        if not self.responses:
            raise LLMError("FakeLLM: brak przygotowanych odpowiedzi")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        tokens_in = sum(len(m["content"]) for m in messages) // 4
        return LLMResult(text=r, tokens_in=tokens_in, tokens_out=len(r) // 4, latency_ms=1.0)
