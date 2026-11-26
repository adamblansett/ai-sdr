import hashlib
import math
import re

import httpx
import structlog
from fastapi import Request

from app.core.config import Settings

logger = structlog.get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def deterministic_embed(text: str, dims: int = 384) -> list[float]:
    """Compute a deterministic L2-normalized dense vector via token + trigram hashing."""
    safe_dims = max(16, dims)
    vec = [0.0] * safe_dims
    normalized = " ".join(text.lower().split())
    if not normalized:
        return vec

    tokens = _TOKEN_RE.findall(normalized)
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % safe_dims
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign * 1.5

    for idx_pos in range(max(0, len(normalized) - 2)):
        trigram = normalized[idx_pos : idx_pos + 3]
        digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % safe_dims
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign * 0.5

    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [round(v / norm, 6) for v in vec]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    if not vec_a or not vec_b:
        return 0.0
    length = min(len(vec_a), len(vec_b))
    dot = sum(vec_a[i] * vec_b[i] for i in range(length))
    norm_a = math.sqrt(sum(vec_a[i] * vec_a[i] for i in range(length)))
    norm_b = math.sqrt(sum(vec_b[i] * vec_b[i] for i in range(length)))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class EmbeddingService:
    """Local-first embedding provider supporting deterministic hashing and Ollama."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dims = settings.embedding_dimensions

    async def embed(self, text: str) -> list[float]:
        """Generate a normalized embedding vector with automatic deterministic fallback."""
        if self.settings.embedding_provider == "ollama":
            try:
                url = f"{self.settings.ollama_base_url.rstrip('/')}/api/embeddings"
                payload = {
                    "model": self.settings.ollama_default_model,
                    "prompt": text,
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    raw_vec = data.get("embedding")
                    if isinstance(raw_vec, list) and raw_vec:
                        return [float(x) for x in raw_vec]
            except Exception as exc:
                logger.warning("ollama_embedding_fallback", error=str(exc))
        return deterministic_embed(text, dims=self.dims)


def get_embedding_service(request: Request) -> EmbeddingService:
    """FastAPI dependency returning the app-scoped EmbeddingService."""
    service = getattr(request.app.state, "embedding_service", None)
    if isinstance(service, EmbeddingService):
        return service
    from app.core.config import get_settings

    return EmbeddingService(get_settings())
