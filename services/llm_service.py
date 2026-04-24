"""Thin orchestration layer over the provider registry.

Historically this module owned both the OpenAI SDK calls and the per-call
error handling. As of the provider refactor, those responsibilities moved
into ``services/providers/``; what stays here is:

  - the JSON-parse helper shared by all chat callers,
  - the feedback-style tweak that mutates the system prompt,
  - the three high-level ``generate_*`` wrappers that bolt the schema
    normalizer on top of a raw provider call.

New backends land entirely inside ``services/providers/``; this module
does not need to change to add one.
"""

from __future__ import annotations

import json
import logging

from prompts.plan_prompt import PLAN_SYSTEM_PROMPT
from prompts.profile_prompt import PROFILE_EXTRACTION_PROMPT
from prompts.review_prompt import REVIEW_SYSTEM_PROMPT
from services.llm_schemas import normalize_plan_feedback, normalize_review_feedback
from services.providers import (
    get_chat_provider,
    get_embedding_provider,
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backwards-compatible helpers
# ---------------------------------------------------------------------------
# ``llm_service`` used to expose several little getters (``get_embedding_backend``,
# ``get_embedding_model_name``, ``get_embedding_runtime_info``,
# ``embedding_enabled``). Downstream modules (tracking, classification, RAG,
# debug panels) import these names directly. We keep them as thin facades over
# the provider so the migration stays zero-churn.


def get_embedding_backend() -> str:
    """Return a short string describing the active embedding backend.

    Values: ``"api"`` when an OpenAI-compatible endpoint is configured,
    ``"local"`` when only the hash fallback is active, ``"disabled"``
    when neither is available.
    """
    provider = get_embedding_provider()
    name = provider.info().name
    if name == "auto_fallback":
        # Composite provider — inspect its primary.
        primary = provider.info().extras.get("primary", {})
        if primary.get("ready"):
            return "api"
        return "local"
    if name == "openai_compat":
        return "api" if provider.info().ready else "disabled"
    if name == "local_hash":
        return "local"
    return "disabled"


def get_embedding_model_name() -> str:
    return get_embedding_provider().info().model or ""


def get_embedding_runtime_info() -> dict:
    """Structured description of the embedding backend for UI panels."""
    info = get_embedding_provider().info()
    backend = get_embedding_backend()
    return {
        "backend": backend,
        "model": info.model,
        "ready": info.ready,
        "note": info.note,
        "provider_name": info.name,
        **{k: v for k, v in info.extras.items() if k in {"primary", "fallback"}},
    }


def embedding_enabled() -> bool:
    provider = get_embedding_provider()
    return bool(provider.enabled and provider.info().ready)


# ---------------------------------------------------------------------------
# Chat + embedding call sites
# ---------------------------------------------------------------------------


def call_api(system_prompt: str, user_content: str) -> str:
    """Call the active chat provider. Return the raw text (possibly an
    error-envelope JSON so existing ``parse_json_safe`` keeps working)."""
    result = get_chat_provider().complete(system_prompt, user_content)
    return result.text


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Slots whose input was empty or failed come back as ``[]``."""
    return get_embedding_provider().embed(texts)


def parse_json_safe(text: str) -> dict | None:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except Exception:
        return None


def _style_instruction(feedback_style: str) -> str:
    style = str(feedback_style or "rational").strip().lower()
    if style == "gentle":
        return "\n补充要求：语气温和、支持、不过度施压，但仍要具体指出问题与动作建议。"
    if style == "strict":
        return "\n补充要求：语气直接、要求更高、少安慰，多指出关键缺口，但不要羞辱或攻击用户。"
    return "\n补充要求：语气理性、克制、分析导向，强调判断依据和可执行动作。"


def generate_plan_feedback(user_content: str, feedback_style: str = "rational") -> dict:
    """Call the plan LLM and normalize its output.

    The normalizer guarantees a canonical dict shape and tags degraded
    responses (parse failure / error envelope / all-empty JSON) with
    ``degraded=True`` + ``degraded_reason`` so the UI can surface the
    failure explicitly instead of rendering raw error text as "总体判断".
    """
    raw = call_api(PLAN_SYSTEM_PROMPT + _style_instruction(feedback_style), user_content)
    data = parse_json_safe(raw)
    return normalize_plan_feedback(data, raw_text=raw)


def generate_review_feedback(user_content: str, feedback_style: str = "rational") -> dict:
    """Call the review LLM and normalize its output. See ``generate_plan_feedback``."""
    raw = call_api(REVIEW_SYSTEM_PROMPT + _style_instruction(feedback_style), user_content)
    data = parse_json_safe(raw)
    return normalize_review_feedback(data, raw_text=raw)


def extract_profile_from_long_text(user_content: str) -> dict:
    raw = call_api(PROFILE_EXTRACTION_PROMPT, user_content)
    data = parse_json_safe(raw)
    if data:
        return {
            "main_goal": str(data.get("main_goal", "") or "").strip(),
            "current_focus": str(data.get("current_focus", "") or "").strip(),
            "priorities": str(data.get("priorities", "") or "").strip(),
            "constraints": str(data.get("constraints", "") or "").strip(),
            "not_urgent": str(data.get("not_urgent", "") or "").strip(),
        }
    return {
        "error": "AI 未能正确提取结构化结果，请手动整理后再保存。",
        "main_goal": "",
        "current_focus": "",
        "priorities": "",
        "constraints": "",
        "not_urgent": "",
        "raw": raw,
    }
