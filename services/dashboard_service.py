from __future__ import annotations

from typing import Any

from config.settings import TODAY
from services.goal_service import compute_goal_stats


def _goal_key(goal: dict) -> str:
    return goal.get("goal_id") or goal.get("goal", "")


def _record_has_review(record: dict) -> bool:
    if not record:
        return False
    if record.get("tomorrow_suggestion"):
        return True
    review_result = record.get("ai_review_result", {})
    return bool(review_result and any(review_result.values()))


def _task_progress(record: dict) -> tuple[int, int]:
    tasks = record.get("tasks", []) if record else []
    done_count = sum(1 for task in tasks if task.get("done"))
    return done_count, len(tasks)


def _latest_tracking(history: list) -> dict:
    for record in reversed(history):
        tracking = record.get("suggestion_tracking", {})
        if tracking and tracking.get("status"):
            return tracking
    return {}


def _goal_alerts(goals: list, history: list) -> list[dict[str, Any]]:
    _, last_map, disc_goals, _, _ = compute_goal_stats(goals, history)
    alerts = []
    for goal in disc_goals[:2]:
        goal_id = _goal_key(goal)
        alerts.append(
            {
                "goal": goal.get("goal", ""),
                "last_date": last_map.get(goal_id) or "从未推进",
                "level": goal.get("level", 3),
            }
        )
    return alerts


def build_dashboard_snapshot(goals: list, history: list, profile: dict) -> dict:
    history = history or []
    today_record = next((record for record in history if record.get("date") == TODAY), {})
    today_ai_plan = today_record.get("ai_plan_result", {}) if today_record else {}
    today_ai_review = today_record.get("ai_review_result", {}) if today_record else {}
    latest_tracking = _latest_tracking(history)

    today_top_priority = (
        today_record.get("top_priority")
        or today_ai_plan.get("top_priority", "")
    )
    today_tomorrow = (
        today_record.get("tomorrow_suggestion")
        or today_ai_review.get("tomorrow", "")
    )

    has_today_tasks = bool(today_record and today_record.get("tasks"))
    has_today_review = _record_has_review(today_record)
    done_count, total_count = _task_progress(today_record)

    if not has_today_tasks:
        workflow_state = "empty"
    elif has_today_review:
        workflow_state = "reviewed"
    else:
        workflow_state = "planned"

    if workflow_state == "reviewed":
        primary_mode = "tomorrow"
        primary_text = today_tomorrow or "今天已经完成复盘，明天先做最关键的下一步。"
        primary_caption = (
            f"今天已复盘，完成 {done_count}/{total_count} 项。"
            if total_count
            else "今天已复盘。"
        )
    elif workflow_state == "planned":
        primary_mode = "top_priority"
        primary_text = today_top_priority or "今天已经有计划，优先守住最重要的一件事。"
        primary_caption = (
            f"今天已安排 {total_count} 项任务，先把最重要的一件事做扎实。"
            if total_count
            else "今天已生成计划。"
        )
    else:
        primary_mode = "empty"
        primary_text = "先把今天最重要的一件事写下来，再决定其余安排。"
        primary_caption = "你还没有保存今天的任务，先做一个轻量计划。"

    latest_top_priority = ""
    latest_tomorrow = ""
    for record in reversed(history):
        if not latest_top_priority:
            latest_top_priority = record.get("top_priority") or record.get("ai_plan_result", {}).get("top_priority", "")
        if not latest_tomorrow:
            latest_tomorrow = record.get("tomorrow_suggestion") or record.get("ai_review_result", {}).get("tomorrow", "")
        if latest_top_priority and latest_tomorrow:
            break

    return {
        "today_record": today_record,
        "workflow_state": workflow_state,
        "primary_mode": primary_mode,
        "primary_text": primary_text,
        "primary_caption": primary_caption,
        "today_top_priority": today_top_priority,
        "today_tomorrow_suggestion": today_tomorrow,
        "latest_top_priority": latest_top_priority,
        "latest_tomorrow_suggestion": latest_tomorrow,
        "latest_tracking": latest_tracking,
        "goal_alerts": _goal_alerts(goals, history),
        "recent_records": history[-3:],
        "current_focus": profile.get("current_focus", ""),
        "constraints": profile.get("constraints", ""),
    }
