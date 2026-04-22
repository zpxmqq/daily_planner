from __future__ import annotations

import datetime as dt
import math
import re
from typing import Iterable


def _goal_lookup(goals: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id = {(goal.get("goal_id") or goal.get("goal", "")): goal for goal in goals}
    by_name = {goal.get("goal", ""): goal for goal in goals if goal.get("goal")}
    return by_id, by_name


def _task_tags(task: dict, goals_by_id: dict[str, dict], goals_by_name: dict[str, dict]) -> list[str]:
    tags = []
    if task.get("tag"):
        tags.append(str(task["tag"]).strip())

    linked_goal = None
    if task.get("goal_id") and task["goal_id"] in goals_by_id:
        linked_goal = goals_by_id[task["goal_id"]]
    elif task.get("goal") and task["goal"] in goals_by_name:
        linked_goal = goals_by_name[task["goal"]]

    if linked_goal:
        tags.extend(linked_goal.get("tags", []))

    ordered = []
    seen = set()
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in seen:
            ordered.append(clean)
            seen.add(clean)
    return ordered


def _compact_join(values: Iterable[str], fallback: str = "") -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return "；".join(cleaned) if cleaned else fallback


def _dedupe(values: Iterable[str]) -> list[str]:
    ordered = []
    seen = set()
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            ordered.append(clean)
            seen.add(clean)
    return ordered


def _extract_keywords(text: str) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", text.lower())
    return {token for token in tokens if len(token) >= 2}


def _safe_date(value: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _serialize_task(task: dict, goals_by_id: dict[str, dict], goals_by_name: dict[str, dict]) -> str:
    parts = [task.get("text", "").strip()]
    if task.get("goal"):
        parts.append(f"目标：{task['goal']}")
    tags = _task_tags(task, goals_by_id, goals_by_name)
    if tags:
        parts.append(f"标签：{', '.join(tags)}")
    if task.get("priority"):
        parts.append(f"优先级：{task['priority']}")
    if task.get("duration") is not None:
        parts.append(f"时长：{task.get('duration', 0)} 分钟")
    actual_minutes = int(task.get("actual_minutes", 0) or 0)
    if actual_minutes > 0:
        parts.append(f"实际用时：{actual_minutes} 分钟")
    if task.get("unplanned"):
        parts.append("突发任务")
    if task.get("must"):
        parts.append("必须完成")
    if task.get("done"):
        parts.append("已完成")
    if task.get("note"):
        parts.append(f"备注：{task['note']}")
    return "；".join(part for part in parts if part)


def _plan_chunk(record: dict, goals: list[dict]) -> dict | None:
    tasks = record.get("tasks", []) or []
    if not tasks and not record.get("plan") and not record.get("top_priority") and not record.get("ai_plan_result"):
        return None

    goals_by_id, goals_by_name = _goal_lookup(goals)
    plan_ai = record.get("ai_plan_result", {}) or {}
    plan_metrics = record.get("plan_metrics", {}) or {}

    goal_ids = _dedupe(task.get("goal_id", "") for task in tasks if task.get("goal_id"))
    tags = _dedupe(
        tag
        for task in tasks
        for tag in _task_tags(task, goals_by_id, goals_by_name)
    )

    task_lines = [_serialize_task(task, goals_by_id, goals_by_name) for task in tasks if task.get("text")]
    issues = plan_ai.get("issues", []) or []
    focus_tasks = plan_ai.get("focus_tasks", []) or []
    adjustments = plan_ai.get("adjustments", []) or []
    top_priority = record.get("top_priority") or plan_ai.get("top_priority", "")

    summary_bits = [
        f"计划重点：{top_priority}" if top_priority else "",
        f"任务数：{len(tasks)}",
        f"总时长：{plan_metrics.get('total_minutes', 0)} 分钟" if plan_metrics else "",
        f"主要问题：{_compact_join(issues)}" if issues else "",
        f"建议调整：{_compact_join(adjustments)}" if adjustments else "",
    ]
    summary_text = _compact_join(summary_bits, fallback="当天有计划记录，但摘要信息较少。")

    source_sections = [
        f"日期：{record.get('date', '')}",
        "类型：晨间计划",
        f"计划摘要：{record.get('plan', '').strip()}",
        "任务列表：\n" + ("\n".join(f"- {line}" for line in task_lines) if task_lines else "- 无"),
        f"AI 总体评价：{plan_ai.get('overall', '').strip()}",
        f"AI 覆盖判断：{plan_ai.get('covers_focus', '').strip()}",
        f"AI 发现问题：{_compact_join(issues)}",
        f"AI 聚焦任务：{_compact_join(focus_tasks)}",
        f"AI 建议调整：{_compact_join(adjustments)}",
        f"最重要的一件事：{top_priority}",
        f"计划负荷：{plan_metrics.get('time_assessment', '')}",
    ]

    return {
        "chunk_id": f"{record.get('date', '')}:plan",
        "record_date": record.get("date", ""),
        "chunk_type": "plan_chunk",
        "source_text": "\n".join(part for part in source_sections if str(part).strip()),
        "summary_text": summary_text,
        "goal_ids": goal_ids,
        "tags": tags,
    }


def _review_chunk(record: dict, goals: list[dict]) -> dict | None:
    tasks = record.get("tasks", []) or []
    review_ai = record.get("ai_review_result", {}) or {}
    tracking = record.get("suggestion_tracking", {}) or {}
    done_tasks = [task for task in tasks if task.get("done")]
    undone_tasks = [task for task in tasks if not task.get("done")]

    has_content = any(
        [
            done_tasks,
            record.get("result", "").strip(),
            review_ai,
            record.get("tomorrow_suggestion", "").strip(),
            tracking.get("status", "").strip(),
        ]
    )
    if not has_content:
        return None

    goals_by_id, goals_by_name = _goal_lookup(goals)
    goal_ids = _dedupe(task.get("goal_id", "") for task in tasks if task.get("goal_id"))
    tags = _dedupe(
        tag
        for task in tasks
        if task.get("done") or task.get("note")
        for tag in _task_tags(task, goals_by_id, goals_by_name)
    )

    done_lines = [_serialize_task(task, goals_by_id, goals_by_name) for task in done_tasks]
    undone_lines = [_serialize_task(task, goals_by_id, goals_by_name) for task in undone_tasks]
    tomorrow = record.get("tomorrow_suggestion") or review_ai.get("tomorrow", "")
    score = review_ai.get("score", "")
    real_progress = review_ai.get("real_progress", "")
    weak_lines = review_ai.get("weak_lines", "")

    summary_bits = [
        f"真实推进：{real_progress}" if real_progress else "",
        f"完成任务：{len(done_tasks)} 项" if done_tasks else "",
        f"薄弱线：{weak_lines}" if weak_lines else "",
        f"明日动作：{tomorrow}" if tomorrow else "",
        f"建议追踪：{tracking.get('status', '')}" if tracking.get("status") else "",
    ]
    summary_text = _compact_join(summary_bits, fallback="当天有复盘记录，但摘要信息较少。")

    source_sections = [
        f"日期：{record.get('date', '')}",
        "类型：晚间复盘",
        "已完成任务：\n" + ("\n".join(f"- {line}" for line in done_lines) if done_lines else "- 无"),
        "未完成任务：\n" + ("\n".join(f"- {line}" for line in undone_lines) if undone_lines else "- 无"),
        f"额外完成内容：{record.get('result', '').strip()}",
        f"今日状态：{record.get('status', '').strip()}",
        f"AI 评分：{score}",
        f"AI 真实推进：{real_progress}",
        f"AI 薄弱线：{weak_lines}",
        f"明日建议：{tomorrow}",
        f"建议追踪状态：{tracking.get('status', '')}",
        f"建议追踪理由：{tracking.get('reason', '')}",
    ]

    return {
        "chunk_id": f"{record.get('date', '')}:review",
        "record_date": record.get("date", ""),
        "chunk_type": "review_chunk",
        "source_text": "\n".join(part for part in source_sections if str(part).strip()),
        "summary_text": summary_text,
        "goal_ids": goal_ids,
        "tags": tags,
    }


def build_rag_chunks_for_record(record: dict, goals: list[dict]) -> list[dict]:
    chunks = []
    for builder in (_plan_chunk, _review_chunk):
        chunk = builder(record, goals)
        if chunk:
            chunks.append(chunk)
    return chunks


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _recency_boost(record_date: str) -> float:
    date_value = _safe_date(record_date)
    if date_value is None:
        return 0.0
    days_ago = max((dt.date.today() - date_value).days, 0)
    if days_ago >= 30:
        return 0.0
    return 0.10 * (1 - days_ago / 30)


def _metadata_overlap_boost(candidate: dict, query_goal_ids: set[str], query_tags: set[str], query_keywords: set[str]) -> float:
    candidate_goal_ids = set(candidate.get("goal_ids", []))
    candidate_tags = set(candidate.get("tags", []))
    candidate_keywords = _extract_keywords(candidate.get("source_text", ""))

    boost = 0.0
    if query_goal_ids and candidate_goal_ids:
        overlap = len(query_goal_ids & candidate_goal_ids)
        if overlap:
            boost += min(0.12, 0.06 * overlap)
    if query_tags and candidate_tags:
        overlap = len({tag.lower() for tag in query_tags} & {tag.lower() for tag in candidate_tags})
        if overlap:
            boost += min(0.08, 0.04 * overlap)
    if query_keywords and candidate_keywords:
        overlap = len(query_keywords & candidate_keywords)
        if overlap:
            boost += min(0.05, 0.01 * overlap)
    return boost


def rank_rag_candidates(
    query_text: str,
    query_embedding: list[float],
    candidates: list[dict],
    goal_ids: list[str] | None = None,
    tags: list[str] | None = None,
    top_k: int = 4,
) -> list[dict]:
    query_goal_ids = {str(goal_id).strip() for goal_id in goal_ids or [] if str(goal_id).strip()}
    query_tags = {str(tag).strip() for tag in tags or [] if str(tag).strip()}
    query_keywords = _extract_keywords(query_text)

    scored = []
    for candidate in candidates:
        semantic = (_cosine_similarity(query_embedding, candidate.get("embedding", [])) + 1) / 2
        recency = _recency_boost(candidate.get("record_date", ""))
        overlap = _metadata_overlap_boost(candidate, query_goal_ids, query_tags, query_keywords)
        total_score = semantic + recency + overlap
        scored.append(
            {
                **candidate,
                "semantic_score": round(semantic, 4),
                "recency_boost": round(recency, 4),
                "metadata_boost": round(overlap, 4),
                "score": round(total_score, 4),
            }
        )

    scored.sort(key=lambda item: (-item["score"], item.get("record_date", "")), reverse=False)
    return scored[:top_k]


def format_rag_context(chunks: list[dict]) -> str:
    if not chunks:
        return ""

    lines = []
    for chunk in chunks:
        label = "晨间计划" if chunk.get("chunk_type") == "plan_chunk" else "晚间复盘"
        lines.append(
            f"- {chunk.get('record_date', '')}｜{label}｜{chunk.get('summary_text', '').strip()}"
        )
    return "【相关历史经验】\n" + "\n".join(lines)
