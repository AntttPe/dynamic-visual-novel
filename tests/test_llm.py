"""Testy warstwy modeli: które adresy i klucze trafiają do LiteLLM (bez prawdziwych wywołań)."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm import litellm_client
from app.llm.base import LLMError
from app.llm.litellm_client import LiteLLMClient, resolve_api_base, resolve_api_key

S = Settings(_env_file=None, ollama_base_url="http://host.docker.internal:11434",
             narrator_api_base="http://host.docker.internal:8001/v1", anthropic_api_key="sk-test")


def test_api_base_and_key_per_provider():
    assert resolve_api_base("ollama_chat/gemma4:12b", S) == "http://host.docker.internal:11434"
    assert resolve_api_base("hosted_vllm/Qwen/Qwen3-8B", S) == "http://host.docker.internal:8001/v1"
    assert resolve_api_base("anthropic/claude-haiku-5-5", S) is None
    assert resolve_api_key("anthropic/claude-haiku-5-5", S) == "sk-test"
    assert resolve_api_key("ollama_chat/gemma4:12b", S) is None


def test_university_proxy_uses_own_base_and_key():
    s = Settings(_env_file=None, narrator_api_base="http://10.0.0.1:4000/v1", narrator_api_key="sk-uczelnia",
                 openai_api_key="sk-openai")
    assert resolve_api_base("openai/strata-big", s) == "http://10.0.0.1:4000/v1"
    assert resolve_api_key("openai/strata-big", s) == "sk-uczelnia"
    assert resolve_api_key("anthropic/x", s) is None


def test_default_model_falls_back_to_ollama_model():
    # narrator_model podany jawnie, bo zmienna NARRATOR_MODEL z .env trafia do środowiska kontenera
    s = Settings(_env_file=None, narrator_model="", ollama_model="gemma4:e4b")
    assert s.default_narrator_model == "ollama_chat/gemma4:e4b"
    assert Settings(_env_file=None, narrator_model="anthropic/x").default_narrator_model == "anthropic/x"


@pytest.mark.anyio
async def test_client_passes_schema_and_reads_usage(monkeypatch):
    seen = {}

    async def fake_acompletion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
        )

    monkeypatch.setattr(litellm_client.litellm, "acompletion", fake_acompletion)
    client = LiteLLMClient("ollama_chat/gemma4:12b", S)
    result = await client.complete([{"role": "user", "content": "hej"}], json_schema={"type": "object"}, seed=7)
    assert result.text == '{"ok": true}'
    assert (result.tokens_in, result.tokens_out) == (120, 30)
    assert seen["api_base"] == "http://host.docker.internal:11434"
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert seen["seed"] == 7


@pytest.mark.anyio
async def test_client_wraps_provider_errors(monkeypatch):
    async def broken(**kwargs):
        raise ConnectionError("odmowa połączenia")

    monkeypatch.setattr(litellm_client.litellm, "acompletion", broken)
    with pytest.raises(LLMError):
        await LiteLLMClient("ollama_chat/x", S).complete([{"role": "user", "content": "hej"}])


@pytest.mark.anyio
async def test_real_ollama_answers():
    """Opcjonalny: przechodzi tylko, gdy Ollama działa i model jest pobrany."""
    from app.config import settings
    from app.llm import ollama_available

    if not await ollama_available(settings.ollama_base_url):
        pytest.skip("Ollama nie działa, pomijam (to nie jest błąd)")
    result = await LiteLLMClient(f"ollama_chat/{settings.ollama_model}", settings).complete(
        [{"role": "user", "content": "Odpowiedz jednym słowem: tak"}], max_tokens=20)
    assert result.text.strip()
    assert result.tokens_out > 0
