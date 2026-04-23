"""Minimal observability utilities.

The app has no structured logs — every degraded path (embedding fallback,
LLM parse failure, classification fallback, tracking low-confidence) is
silent, which makes self-debug and demo walkthroughs fragile.

This module provides a single place to:
  1. Install a reasonable ``logging.basicConfig`` exactly once.
  2. Record named events with a small payload so the UI can surface a
     minimalist "本次运行发生的降级/异常" panel without each caller inventing
     its own format.

Usage::

    from services.metrics import log_event
    log_event("tracking.embedding_fallback", {"similarity": 0.74})

The buffer lives in a module-level list bounded to the last 50 events to
keep memory bounded.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any

_LOG_LEVEL = os.environ.get("PLANNER_LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s — %(message)s"

_configured = False
_lock = threading.Lock()
_event_buffer: deque[dict[str, Any]] = deque(maxlen=50)

_LOGGER = logging.getLogger("daily_planner.metrics")


def _configure_once() -> None:
    global _configured
    if _configured:
        return
    with _lock:
        if _configured:
            return
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            logging.basicConfig(level=_LOG_LEVEL, format=_LOG_FORMAT)
        else:
            root_logger.setLevel(_LOG_LEVEL)
        _configured = True


def log_event(name: str, payload: dict | None = None, *, level: str = "info") -> None:
    """Record a named event and emit it via the standard logging system.

    ``name`` is a dotted key (``tracking.embedding_fallback``); ``payload``
    is an optional small dict that gets stringified into the log line.
    """
    _configure_once()
    entry = {
        "ts": time.time(),
        "name": name,
        "payload": payload or {},
    }
    _event_buffer.append(entry)

    log_fn = getattr(_LOGGER, level, _LOGGER.info)
    if payload:
        log_fn("%s %s", name, payload)
    else:
        log_fn("%s", name)


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    """Return up to ``limit`` most-recent events (newest last)."""
    events = list(_event_buffer)
    return events[-limit:]


def clear_events() -> None:
    _event_buffer.clear()
