"""EmbeddingClient — Protocol + impls (OpenAI, Null fallback).

Decisões:
- Protocol comum permite trocar provider via env (ex: voyage no futuro).
- NullEmbeddingClient devolve zeros — útil para rodar a pipeline em CI
  ou em dev sem chave; também detecta bugs lógicos cedo (toda issue vira
  trivialmente similar a si mesma e nada mais).
- Embedding em batch (uma chamada por job) — text-embedding-3-small
  aceita até 2048 inputs por request.
"""

import hashlib
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def issue_text_for_embedding(summary: str, description: str | None) -> str:
    """Concatena os campos textuais que entram no embedding.

    Mantém em uma função separada para garantir consistência entre o
    texto embedded e o text_hash usado para detectar mudanças.
    """
    return (summary + "\n\n" + (description or "")).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@runtime_checkable
class EmbeddingClient(Protocol):
    model: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str, model: str, dim: int):
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # text-embedding-3-* aceita parâmetro `dimensions` para reduzir
        # vetores nativos. Mantemos consistente com settings.embedding_dim.
        resp = await self._client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dim,
        )
        return [d.embedding for d in resp.data]

    async def close(self) -> None:
        await self._client.close()


class NullEmbeddingClient:
    """Devolve vetores zerados — placeholder para rodar sem API key."""

    model = "null-embedding"

    def __init__(self, dim: int):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]

    async def close(self) -> None:
        return None


def make_embedding_client() -> EmbeddingClient:
    if settings.openai_api_key:
        log.info("embedding_client", impl="openai", model=settings.embedding_model)
        return OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    log.warning(
        "embedding_client_null",
        reason="OPENAI_API_KEY ausente — pipeline roda mas similaridade não funciona",
    )
    return NullEmbeddingClient(dim=settings.embedding_dim)
