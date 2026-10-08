from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import llm
from app.config import settings

app = FastAPI(title="Dynamic Visual Novel")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None


@app.get("/api/health")
async def health() -> dict:
    """Sprawdza, czy aplikacja działa i które providery LLM są dostępne."""
    return {
        "status": "ok",
        "providers": {
            "anthropic": bool(settings.anthropic_api_key),
            "openai": bool(settings.openai_api_key),
            "gemini": bool(settings.gemini_api_key),
            "ollama": await llm.ollama_available(),
        },
        "ollama_model": settings.ollama_model,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    try:
        reply = await llm.ollama_chat([m.model_dump() for m in req.messages], req.model)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama niedostępna lub błąd modelu: {e}") from e
    return {"reply": reply}


# UI: pliki statyczne serwowane pod "/" (montowane na końcu, żeby nie przykryć /api)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
