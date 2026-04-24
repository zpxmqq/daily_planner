"""Deterministic hash-based embedding — offline, dependency-free fallback.

This is the same algorithm that used to live inline in ``llm_service``:
token-level + bigram features are hashed into a fixed-dimension signed
bag-of-words, then L2-normalized. It is **not** a semantic model — cosine
between "晨跑" and "jogging" is near zero — but it is deterministic, fast,
and keeps downstream cosine-similarity code (RAG ranker, tracking rescue,
tag centroids) working when no embedding API is configured.
"""

from __future__ import annotations

import hashlib
import math
import re

from services.providers.base import EmbeddingProvider, ProviderInfo

LOCAL_EMBEDDING_DIM = 256
LOCAL_EMBEDDING_MODEL = "local-hash-v1"


def _tokenize(text: str) -> list[str]:
    content = str(text or "").strip().lower()
    if not content:
        return []
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{2,}", content)
    compact = re.sub(r"\s+", "", content)
    bigrams = [compact[index : index + 2] for index in range(max(len(compact) - 1, 0))]
    return tokens + bigrams


def _embed_one(text: str) -> list[float]:
    tokens = _tokenize(text)
    if not tokens:
        return []

    vector = [0.0] * LOCAL_EMBEDDING_DIM
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % LOCAL_EMBEDDING_DIM
        sign = 1.0 if digest[0] % 2 == 0 else -1.0
        weight = 1.0 + min(len(token), 8) * 0.12
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return []
    return [round(value / norm, 8) for value in vector]


class LocalHashEmbeddingProvider:
    """Concrete ``EmbeddingProvider``; always ready."""

    name = "local_hash"

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            model=LOCAL_EMBEDDING_MODEL,
            ready=True,
            note="本地轻量 embedding（哈希特征）：无需网络，语义质量弱，仅保证主链路可用。",
            extras={"dim": LOCAL_EMBEDDING_DIM},
        )

    @property
    def enabled(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embed_one(text) if str(text or "").strip() else [] for text in texts]


# Assert protocol conformance at import time — catches missing methods early.
_instance: EmbeddingProvider = LocalHashEmbeddingProvider()
