"""Provider protocols — what every chat / embedding backend must implement.

We use ``typing.Protocol`` rather than ABCs so providers don't need to
inherit anything. This keeps the door open for later adding a provider
implementation that wraps a 3rd-party package whose class we don't own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ProviderInfo:
    """Metadata the UI / evals show to explain which backend is active."""

    name: str              # e.g. "openai_compat"
    model: str             # e.g. "deepseek-chat" or "text-embedding-3-small"
    ready: bool            # False when config is missing and there's no fallback
    note: str = ""         # human-readable line for the UI
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "ready": self.ready,
            "note": self.note,
            **self.extras,
        }


@dataclass
class ChatResult:
    """The raw text a chat provider returned, plus a structured error flag.

    Callers should treat ``error`` as authoritative — when ``error`` is a
    non-empty string, ``text`` still contains a JSON ``{"error": "..."}``
    envelope so downstream normalizers keep working unchanged.
    """

    text: str
    error: str = ""


@runtime_checkable
class LLMProvider(Protocol):
    """Chat-completion backend."""

    def info(self) -> ProviderInfo: ...

    def complete(self, system_prompt: str, user_content: str) -> ChatResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Vectorization backend.

    ``embed(texts)`` must return a list of the same length as ``texts``,
    each slot either a list[float] embedding or ``[]`` (meaning "I could
    not embed this input — caller should treat as missing"). Empty inputs
    get ``[]`` as well.
    """

    def info(self) -> ProviderInfo: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def enabled(self) -> bool: ...
