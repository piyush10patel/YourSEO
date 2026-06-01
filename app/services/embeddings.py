"""Embedding client for the knowledge graph (spec §8 storage: Postgres+pgvector).

Thin async wrapper over Ollama's embeddings endpoint. Disabled by default
(`SEO_EMBEDDINGS_ENABLED`) — clustering falls back to the lexical method — so
the system needs no extra model pull out of the box. Enable it and
`ollama pull nomic-embed-text` to populate `keywords.embedding` for semantic
clustering / similarity.
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import LLMConnectionError, LLMResponseError

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._owns = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.ollama_base_url,
            timeout=httpx.Timeout(self.settings.ollama_timeout),
        )

    async def __aenter__(self) -> "EmbeddingClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns:
            await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        payload = {"model": self.settings.embed_model, "prompt": text}
        try:
            resp = await self._client.post("/api/embeddings", json=payload)
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Could not reach Ollama embeddings at {self.settings.ollama_base_url}.",
                detail=str(exc),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMResponseError(
                f"Embeddings request failed (HTTP {exc.response.status_code}).",
                detail=str(exc),
            ) from exc
        data = resp.json()
        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise LLMResponseError("Embeddings response missing 'embedding'.")
        return embedding
