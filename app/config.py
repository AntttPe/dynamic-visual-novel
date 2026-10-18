from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1:8b"
    data_dir: str = "data"

    # Narrator: model w formacie LiteLLM "<provider>/<model>", np. ollama_chat/gemma4:12b,
    # hosted_vllm/Qwen/Qwen3-8B, anthropic/claude-haiku-5-5. Puste = Ollama z OLLAMA_MODEL.
    narrator_model: str = ""
    # Adres serwera zgodnego z API OpenAI dla modeli "openai/..." i "hosted_vllm/..."
    # (np. serwer uczelni albo vLLM na wynajętym GPU). Dla Ollamy używamy OLLAMA_BASE_URL.
    narrator_api_base: str = ""
    # Klucz do tego serwera. Puste = OPENAI_API_KEY.
    narrator_api_key: str = ""
    narrator_temperature: float = 0.7
    narrator_max_tokens: int = 1200
    narrator_timeout_s: float = 180
    narrator_json_retries: int = 2

    # Pamięć narratora: "full" (pełna historia) albo "window" (ostatnie N tur)
    memory_history: str = "window"
    memory_window: int = 8
    memory_state_in_prompt: bool = True

    @property
    def default_narrator_model(self) -> str:
        return self.narrator_model or f"ollama_chat/{self.ollama_model}"


settings = Settings()
