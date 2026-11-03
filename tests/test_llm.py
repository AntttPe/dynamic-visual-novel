"""Testy warstwy modeli: które adresy i klucze trafiają do LiteLLM (bez prawdziwych wywołań)."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm import litellm_client
from app.llm.base import LLMError
from app.llm.litellm_client import LiteLLMClient, answer_started, resolve_api_base, resolve_api_key

S = Settings(_env_file=None, ollama_base_url="http://host.docker.internal:11434",
             narrator_api_base="http://host.docker.internal:8001/v1", anthropic_api_key="sk-test",
             narrator_stream=False)
S_STREAM = S.model_copy(update={"narrator_stream": True})


def _chunk(content=None, reasoning=None, usage=None):
    choices = [] if content is None and reasoning is None else [
        SimpleNamespace(delta=SimpleNamespace(content=content, reasoning_content=reasoning))]
    return SimpleNamespace(choices=choices, usage=usage)


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield c
    return gen()


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
async def test_stream_joins_text_and_measures_ttft(monkeypatch):
    seen = {}
    usage = SimpleNamespace(prompt_tokens=500, completion_tokens=9,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=400))

    async def fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _stream([_chunk(reasoning="myślę"), _chunk(content='{"ok"'), _chunk(content=": true}"),
                        _chunk(usage=usage)])

    monkeypatch.setattr(litellm_client.litellm, "acompletion", fake_acompletion)
    result = await LiteLLMClient("openai/strata-big", S_STREAM).complete([{"role": "user", "content": "hej"}])
    assert seen["stream"] is True and seen["stream_options"] == {"include_usage": True}
    assert result.text == '{"ok": true}'
    assert (result.tokens_in, result.tokens_out, result.tokens_cached) == (500, 9, 400)
    assert result.ttft_ms is not None and result.first_answer_ms is not None
    assert result.ttft_ms <= result.first_answer_ms <= result.latency_ms


@pytest.mark.anyio
async def test_stream_without_usage_and_answer(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _stream([_chunk(reasoning="tylko myślenie")])

    monkeypatch.setattr(litellm_client.litellm, "acompletion", fake_acompletion)
    result = await LiteLLMClient("openai/x", S_STREAM).complete([{"role": "user", "content": "hej"}], max_tokens=1)
    assert result.text == "" and result.tokens_in == 0
    assert result.ttft_ms is not None and result.first_answer_ms is None


@pytest.mark.anyio
async def test_stream_ttft_falls_back_to_first_chunk(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _stream([_chunk(content=""), _chunk(usage=SimpleNamespace(prompt_tokens=5, completion_tokens=1))])

    monkeypatch.setattr(litellm_client.litellm, "acompletion", fake_acompletion)
    result = await LiteLLMClient("openai/x", S_STREAM).complete([{"role": "user", "content": "hej"}], max_tokens=1)
    assert result.ttft_ms is not None and result.first_answer_ms is None


@pytest.mark.anyio
async def test_stream_errors_become_llm_error(monkeypatch):
    async def broken_stream():
        yield _chunk(content="{")
        raise ConnectionError("zerwane połączenie")

    async def fake_acompletion(**kwargs):
        return broken_stream()

    monkeypatch.setattr(litellm_client.litellm, "acompletion", fake_acompletion)
    with pytest.raises(LLMError):
        await LiteLLMClient("openai/x", S_STREAM).complete([{"role": "user", "content": "hej"}])


def test_answer_started_skips_think_block():
    assert not answer_started("")
    assert not answer_started("  <thi")
    assert not answer_started("<think>planuję")
    assert not answer_started("<think>planuję</think>\n")
    assert answer_started("<think>planuję</think>{")
    assert answer_started('{"narration"')


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
