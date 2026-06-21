"""Thin async client for Ollama. Local inference only — no external AI APIs."""
from __future__ import annotations

import json

import httpx

from app.core.config import settings


class OllamaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.ollama_url).rstrip("/")

    async def chat_json(self, model: str, system: str, user: str, timeout: float = 30.0) -> dict:
        """Chat completion constrained to JSON output (intent detection)."""
        payload = {
            "model": model,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            return json.loads(content)

    async def chat_text(self, model: str, system: str, user: str, timeout: float = 60.0) -> str:
        """Free-form chat completion (response rendering)."""
        payload = {
            "model": model,
            "stream": False,
            "options": {"temperature": 0.4, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()

    async def embed(self, model: str, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/embeddings", json={"model": model, "prompt": text}
            )
            resp.raise_for_status()
            return resp.json()["embedding"]


ollama = OllamaClient()
