import json
import logging
import math
import os
import re
import hashlib

import streamlit as st
from openai import OpenAI

from config.settings import (
    BASE_URL,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL,
    LOCAL_EMBEDDING_FALLBACK,
    MODEL_NAME,
)
from prompts.plan_prompt import PLAN_SYSTEM_PROMPT
from prompts.profile_prompt import PROFILE_EXTRACTION_PROMPT
from prompts.review_prompt import REVIEW_SYSTEM_PROMPT
from services.llm_schemas import normalize_plan_feedback, normalize_review_feedback
from services.metrics import log_event

LOGGER = logging.getLogger(__name__)
LOCAL_EMBEDDING_MODEL = "local-hash-v1"
_LOCAL_EMBEDDING_DIM = 256


@st.cache_resource
def get_client():
    return OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=BASE_URL)


@st.cache_resource
def get_embedding_client():
    api_key = EMBEDDING_API_KEY or os.getenv("EMBEDDING_API_KEY", "").strip()
    if not api_key:
        return None

    base_url = EMBEDDING_BASE_URL or os.getenv("EMBEDDING_BASE_URL", "").strip()
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def get_embedding_backend() -> str:
    api_key = EMBEDDING_API_KEY or os.getenv("EMBEDDING_API_KEY", "").strip()
    if api_key:
        return "api"
    if LOCAL_EMBEDDING_FALLBACK:
        return "local"
    return "disabled"


def get_embedding_model_name() -> str:
    if get_embedding_backend() == "api":
        return EMBEDDING_MODEL or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
    if get_embedding_backend() == "local":
        return LOCAL_EMBEDDING_MODEL
    return ""


def get_embedding_runtime_info() -> dict:
    backend = get_embedding_backend()
    return {
        "backend": backend,
        "model": get_embedding_model_name(),
        "ready": backend in {"api", "local"},
        "note": (
            "当前使用 API embedding。"
            if backend == "api"
            else "当前使用本地轻量 embedding fallback。"
            if backend == "local"
            else "当前未启用 embedding。"
        ),
    }


def embedding_enabled() -> bool:
    return get_embedding_backend() in {"api", "local"}


def _tokenize_for_local_embedding(text: str) -> list[str]:
    content = str(text or "").strip().lower()
    if not content:
        return []

    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{2,}", content)
    compact = re.sub(r"\s+", "", content)
    bigrams = [compact[index : index + 2] for index in range(max(len(compact) - 1, 0))]
    return tokens + bigrams


def _local_embed_text(text: str) -> list[float]:
    tokens = _tokenize_for_local_embedding(text)
    if not tokens:
        return []

    vector = [0.0] * _LOCAL_EMBEDDING_DIM
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % _LOCAL_EMBEDDING_DIM
        sign = 1.0 if digest[0] % 2 == 0 else -1.0
        weight = 1.0 + min(len(token), 8) * 0.12
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return []
    return [round(value / norm, 8) for value in vector]


def call_api(system_prompt: str, user_content: str) -> str:
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            timeout=30,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        if "timeout" in str(exc).lower():
            log_event("llm.call_timeout", {"model": MODEL_NAME}, level="warning")
            return '{"error":"请求超时，请稍后重试。"}'
        log_event(
            "llm.call_failed",
            {"model": MODEL_NAME, "error": str(exc)[:200]},
            level="warning",
        )
        return json.dumps({"error": f"调用失败：{exc}"}, ensure_ascii=False)


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = [[] for _ in texts]
    indexed_texts = [(index, text.strip()) for index, text in enumerate(texts) if str(text).strip()]
    if not indexed_texts:
        return vectors

    backend = get_embedding_backend()
    if backend == "local":
        for index, text in indexed_texts:
            vectors[index] = _local_embed_text(text)
        return vectors

    client = get_embedding_client()
    if client is None:
        return vectors

    try:
        response = client.embeddings.create(
            model=get_embedding_model_name(),
            input=[text for _, text in indexed_texts],
            timeout=30,
        )
        for (index, _), item in zip(indexed_texts, response.data):
            vectors[index] = item.embedding
    except Exception as exc:
        LOGGER.warning("Embedding request failed: %s", exc)
        log_event(
            "embedding.api_failed",
            {"model": get_embedding_model_name(), "error": str(exc)[:200]},
            level="warning",
        )
        if LOCAL_EMBEDDING_FALLBACK:
            log_event("embedding.local_fallback_used", {"reason": "api_failed"})
            for index, text in indexed_texts:
                vectors[index] = _local_embed_text(text)
    return vectors


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
