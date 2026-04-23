"""Normalize LLM JSON outputs into canonical, typed dicts.

The LLM may return any of:
  (a) valid full JSON with all fields,
  (b) valid JSON with some keys missing or wrong types (``issues`` as a
      string instead of a list, etc.),
  (c) valid JSON with an ``error`` envelope (timeout / provider failure),
  (d) text that cannot be parsed as JSON at all.

Without normalization the UI leaks these failure modes as "content":
e.g. a timeout message ends up rendered as the ``overall`` judgment
because the old ``generate_plan_feedback`` fell back to
``{"overall": raw, ...}``.

These normalizers produce a canonical dict plus a ``degraded`` flag so
the UI can explicitly surface "this is a fallback, not real analysis"
rather than silently rendering blank sections.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)

PLAN_FIELDS_STR = ("overall", "covers_focus", "time_assessment", "top_priority")
PLAN_FIELDS_LIST = ("issues", "focus_tasks", "adjustments")

REVIEW_FIELDS_STR = ("score", "real_progress", "weak_lines", "tomorrow", "focus_insight")


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(_as_str(item) for item in value if item)
    return str(value).strip()


def _as_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        # Be tolerant of a model that emitted a delimited string where a list
        # was asked for — split on common Chinese/Latin separators.
        for sep in ("；", ";", "\n"):
            if sep in value:
                parts = [segment.strip() for segment in value.split(sep)]
                return [segment for segment in parts if segment]
        return [value.strip()]
    return []


def _all_empty(fields_str: dict, fields_list: dict) -> bool:
    has_str = any(bool(value) for value in fields_str.values())
    has_list = any(bool(items) for items in fields_list.values())
    return not (has_str or has_list)


def _extract_error(raw_data) -> str:
    """Detect the API-level error envelope produced by ``call_api``."""
    if not isinstance(raw_data, dict):
        return ""
    error = raw_data.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return ""


def _empty_plan_shell() -> dict:
    return {
        "overall": "",
        "covers_focus": "",
        "time_assessment": "",
        "top_priority": "",
        "issues": [],
        "focus_tasks": [],
        "adjustments": [],
    }


def _empty_review_shell() -> dict:
    return {
        "score": "",
        "real_progress": "",
        "weak_lines": "",
        "tomorrow": "",
        "focus_insight": "",
    }


def normalize_plan_feedback(raw_data, raw_text: str = "") -> dict:
    """Return canonical plan feedback + ``degraded`` / ``error`` flags."""
    if raw_data is None or not isinstance(raw_data, dict):
        LOGGER.warning(
            "Plan feedback fell through: unparseable LLM output (len=%d)",
            len(raw_text or ""),
        )
        return {
            **_empty_plan_shell(),
            "degraded": True,
            "degraded_reason": "AI 返回内容无法解析为 JSON",
            "raw_excerpt": (raw_text or "")[:200],
        }

    error_message = _extract_error(raw_data)
    if error_message:
        LOGGER.warning("Plan feedback error envelope: %s", error_message)
        return {
            **_empty_plan_shell(),
            "error": error_message,
            "degraded": True,
            "degraded_reason": error_message,
        }

    fields_str = {key: _as_str(raw_data.get(key)) for key in PLAN_FIELDS_STR}
    fields_list = {key: _as_str_list(raw_data.get(key)) for key in PLAN_FIELDS_LIST}

    if _all_empty(fields_str, fields_list):
        LOGGER.warning("Plan feedback content empty (raw len=%d)", len(raw_text or ""))
        return {
            **_empty_plan_shell(),
            "degraded": True,
            "degraded_reason": "AI 输出字段几乎全为空，可能触发了模型 guardrail",
            "raw_excerpt": (raw_text or "")[:200],
        }

    normalized = {**fields_str, **fields_list, "degraded": False}
    if not fields_str["top_priority"]:
        normalized["missing_top_priority"] = True
    return normalized


def normalize_review_feedback(raw_data, raw_text: str = "") -> dict:
    """Return canonical review feedback + ``degraded`` / ``error`` flags."""
    if raw_data is None or not isinstance(raw_data, dict):
        LOGGER.warning(
            "Review feedback fell through: unparseable LLM output (len=%d)",
            len(raw_text or ""),
        )
        return {
            **_empty_review_shell(),
            "degraded": True,
            "degraded_reason": "AI 返回内容无法解析为 JSON",
            "raw_excerpt": (raw_text or "")[:200],
        }

    error_message = _extract_error(raw_data)
    if error_message:
        LOGGER.warning("Review feedback error envelope: %s", error_message)
        return {
            **_empty_review_shell(),
            "error": error_message,
            "degraded": True,
            "degraded_reason": error_message,
        }

    fields_str = {key: _as_str(raw_data.get(key)) for key in REVIEW_FIELDS_STR}

    if _all_empty(fields_str, {}):
        LOGGER.warning("Review feedback content empty (raw len=%d)", len(raw_text or ""))
        return {
            **_empty_review_shell(),
            "degraded": True,
            "degraded_reason": "AI 输出字段几乎全为空，可能触发了模型 guardrail",
            "raw_excerpt": (raw_text or "")[:200],
        }

    normalized = {**fields_str, "degraded": False}
    if not fields_str["tomorrow"]:
        normalized["missing_tomorrow"] = True
    return normalized
