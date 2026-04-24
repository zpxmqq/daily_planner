"""OpenAI-compatible chat & embedding providers.

Any endpoint that speaks the OpenAI HTTP schema slots in here — DeepSeek,
OpenAI itself, Moonshot, Zhipu bigmodel v4, local vLLM / Ollama-OpenAI,
etc. A user picks a concrete backend by setting the usual env vars
(``DEEPSEEK_API_KEY`` + ``BASE_URL`` for chat, ``EMBEDDING_API_KEY`` +
``EMBEDDING_BASE_URL`` + ``EMBEDDING_MODEL`` for embedding).

The two classes cache the underlying ``OpenAI`` client in-instance rather
than via ``st.cache_resource``. Providers are themselves cached by the
registry, so we don't need a second caching layer, and keeping
``streamlit`` out of this module makes it unit-testable without a UI.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from openai import OpenAI

from config.settings import (
    BASE_URL,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL,
    MODEL_NAME,
)
from services.metrics import log_event
from services.providers.base import (
    ChatResult,
    EmbeddingProvider,
    LLMProvider,
    ProviderInfo,
)

LOGGER = logging.getLogger(__name__)


class OpenAICompatChatProvider:
    """Chat completion over an OpenAI-compatible endpoint."""

    name = "openai_compat"

    def __init__(self) -> None:
        self._client: Optional[OpenAI] = None
        self._api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self._base_url = BASE_URL
        self._model = MODEL_NAME

    def _get_client(self) -> Optional[OpenAI]:
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def info(self) -> ProviderInfo:
        ready = bool(self._api_key)
        return ProviderInfo(
            name=self.name,
            model=self._model,
            ready=ready,
            note=(
                f"Chat 后端 {self._base_url}，模型 {self._model}。"
                if ready
                else "未配置 DEEPSEEK_API_KEY；chat 将无法调用。"
            ),
        )

    def complete(self, system_prompt: str, user_content: str) -> ChatResult:
        client = self._get_client()
        if client is None:
            message = "未配置 DEEPSEEK_API_KEY，无法调用 LLM。"
            return ChatResult(
                text=json.dumps({"error": message}, ensure_ascii=False),
                error=message,
            )

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                timeout=30,
            )
            return ChatResult(text=response.choices[0].message.content or "")
        except Exception as exc:
            error_text = str(exc)
            if "timeout" in error_text.lower():
                log_event("llm.call_timeout", {"model": self._model}, level="warning")
                return ChatResult(
                    text='{"error":"请求超时，请稍后重试。"}',
                    error="请求超时",
                )
            log_event(
                "llm.call_failed",
                {"model": self._model, "error": error_text[:200]},
                level="warning",
            )
            return ChatResult(
                text=json.dumps({"error": f"调用失败：{exc}"}, ensure_ascii=False),
                error=error_text[:200],
            )


class OpenAICompatEmbeddingProvider:
    """Embedding over an OpenAI-compatible endpoint."""

    name = "openai_compat"

    def __init__(self) -> None:
        self._client: Optional[OpenAI] = None
        self._api_key = EMBEDDING_API_KEY or os.getenv("EMBEDDING_API_KEY", "").strip()
        self._base_url = EMBEDDING_BASE_URL or os.getenv("EMBEDDING_BASE_URL", "").strip()
        self._model = (
            EMBEDDING_MODEL
            or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Optional[OpenAI]:
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        kwargs: dict = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            model=self._model,
            ready=self.enabled,
            note=(
                f"Embedding 后端 {self._base_url or '(默认 OpenAI)'}，模型 {self._model}。"
                if self.enabled
                else "未配置 EMBEDDING_API_KEY；将由 local_hash 兜底。"
            ),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return vectors aligned with ``texts``; empty slot = not embedded."""
        vectors: list[list[float]] = [[] for _ in texts]
        indexed = [(i, str(t).strip()) for i, t in enumerate(texts) if str(t).strip()]
        if not indexed:
            return vectors

        client = self._get_client()
        if client is None:
            return vectors

        try:
            response = client.embeddings.create(
                model=self._model,
                input=[text for _, text in indexed],
                timeout=30,
            )
            for (i, _), item in zip(indexed, response.data):
                vectors[i] = item.embedding
        except Exception as exc:
            LOGGER.warning("Embedding request failed: %s", exc)
            log_event(
                "embedding.api_failed",
                {"model": self._model, "error": str(exc)[:200]},
                level="warning",
            )
            # Deliberately leave slots empty — the registry layer layers a
            # local_hash fallback on top based on LOCAL_EMBEDDING_FALLBACK.
        return vectors


# Protocol conformance check.
_chat_check: LLMProvider = OpenAICompatChatProvider()
_embed_check: EmbeddingProvider = OpenAICompatEmbeddingProvider()
