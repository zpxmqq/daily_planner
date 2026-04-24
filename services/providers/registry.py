"""Singleton registry that picks the active chat / embedding provider.

Selection rules (kept deliberately dumb so config-to-behaviour is obvious):

  - chat: always OpenAI-compatible. If more providers appear later, we
    branch on ``os.getenv("LLM_PROVIDER")`` here.
  - embedding: if ``EMBEDDING_API_KEY`` is set, use OpenAI-compatible.
    Otherwise fall through to ``local_hash`` if
    ``LOCAL_EMBEDDING_FALLBACK`` is enabled (the default). If explicitly
    disabled, return a null provider — callers that ask for embeddings
    will receive empty vectors and the existing defensive code paths
    (RAG skips, tracking skips rescue) kick in naturally.

We also support an **auto-fallback** composite: the live OpenAI embedding
path may fail at request time (rate limit, 500, network), in which case
we want the per-call fallback to local_hash without reconfiguring the
whole app. That behaviour lives in ``AutoFallbackEmbeddingProvider``.
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import LOCAL_EMBEDDING_FALLBACK
from services.metrics import log_event
from services.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    ProviderInfo,
)
from services.providers.local_hash import LocalHashEmbeddingProvider
from services.providers.openai_compat import (
    OpenAICompatChatProvider,
    OpenAICompatEmbeddingProvider,
)

LOGGER = logging.getLogger(__name__)


class AutoFallbackEmbeddingProvider:
    """Wrap a primary provider; fill empty slots with a fallback.

    This lets us say "API embedding is preferred, but when a single batch
    returns nothing — even if the whole provider is nominally ready — we
    fill in with local_hash rather than returning a pile of empty vectors
    that would silently break cosine-similarity math downstream."
    """

    name = "auto_fallback"

    def __init__(
        self,
        primary: EmbeddingProvider,
        fallback: EmbeddingProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def enabled(self) -> bool:
        # Whether the wrapped chain can produce vectors at all.
        return bool(self._primary.enabled) or bool(self._fallback.enabled)

    def info(self) -> ProviderInfo:
        primary_info = self._primary.info()
        fallback_info = self._fallback.info()
        ready = primary_info.ready or fallback_info.ready
        return ProviderInfo(
            name=self.name,
            model=primary_info.model if primary_info.ready else fallback_info.model,
            ready=ready,
            note=(
                f"主：{primary_info.note} | 兜底：{fallback_info.note}"
                if primary_info.ready
                else f"主未就绪，直接使用兜底：{fallback_info.note}"
            ),
            extras={
                "primary": primary_info.to_dict(),
                "fallback": fallback_info.to_dict(),
            },
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Short-circuit when primary is unconfigured — no point calling out.
        if not self._primary.enabled:
            return self._fallback.embed(texts)

        vectors = self._primary.embed(texts)

        # Which slots genuinely wanted an embedding but didn't get one?
        needs_fallback_indices = [
            i
            for i, (text, vec) in enumerate(zip(texts, vectors))
            if str(text or "").strip() and not vec
        ]
        if not needs_fallback_indices:
            return vectors

        log_event(
            "embedding.local_fallback_used",
            {
                "reason": "primary_returned_empty",
                "filled": len(needs_fallback_indices),
                "total": len(texts),
            },
        )
        fallback_texts = [texts[i] for i in needs_fallback_indices]
        filled = self._fallback.embed(fallback_texts)
        for i, vec in zip(needs_fallback_indices, filled):
            vectors[i] = vec
        return vectors


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
# We cache a single instance per provider across the process rather than per
# Streamlit session. Providers are stateless aside from the OpenAI client
# handle they hold, and re-creating them cost essentially nothing, but
# dozens of Streamlit reruns per session * 2 providers = noticeable churn.

_chat_provider: Optional[LLMProvider] = None
_embedding_provider: Optional[EmbeddingProvider] = None


def get_chat_provider() -> LLMProvider:
    global _chat_provider
    if _chat_provider is None:
        _chat_provider = OpenAICompatChatProvider()
    return _chat_provider


def _build_embedding_provider() -> EmbeddingProvider:
    primary = OpenAICompatEmbeddingProvider()
    if not LOCAL_EMBEDDING_FALLBACK:
        return primary
    fallback = LocalHashEmbeddingProvider()
    if not primary.enabled:
        # No API configured → just use local_hash directly. Wrapping it in
        # AutoFallback would work but the extra indirection isn't earning
        # anything.
        return fallback
    return AutoFallbackEmbeddingProvider(primary=primary, fallback=fallback)


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = _build_embedding_provider()
    return _embedding_provider


def reset_providers() -> None:
    """Test hook — drop cached providers so env-var changes take effect."""
    global _chat_provider, _embedding_provider
    _chat_provider = None
    _embedding_provider = None
