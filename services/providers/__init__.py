"""Provider abstraction for LLM chat and embedding backends.

Prior to this package, ``services/llm_service`` reached directly into
``openai.OpenAI`` with a handful of env-var checks scattered across four
helpers (``get_client``, ``get_embedding_client``, ``get_embedding_backend``,
``get_embedding_model_name``). Adding a new backend (a local BGE server, a
Zhipu API, an Ollama instance) meant editing four places and still left
``llm_service`` owning the OpenAI-SDK call site.

This package keeps one rule: **one file per provider**. A provider implements
the ``EmbeddingProvider`` or ``LLMProvider`` protocol in ``base.py`` and the
registry in ``registry.py`` picks it up from config.

Current providers:
  - ``openai_compat`` — any OpenAI-compatible chat/embedding endpoint
                        (DeepSeek, OpenAI, Moonshot, Zhipu bigmodel v4, ...)
  - ``local_hash``     — deterministic hash-based embedding fallback; no
                        network, no heavy deps. Poor semantic quality but
                        keeps RAG & tracking functional offline.

Downstream code (``llm_service``, ``tracking_service``, ``rag_service``,
``classification_service``) never imports a provider directly — always via
``get_chat_provider()`` / ``get_embedding_provider()`` from the registry.
"""

from services.providers.base import (
    ChatResult,
    EmbeddingProvider,
    LLMProvider,
    ProviderInfo,
)
from services.providers.registry import (
    get_chat_provider,
    get_embedding_provider,
    reset_providers,  # test-only
)

__all__ = [
    "ChatResult",
    "EmbeddingProvider",
    "LLMProvider",
    "ProviderInfo",
    "get_chat_provider",
    "get_embedding_provider",
    "reset_providers",
]
