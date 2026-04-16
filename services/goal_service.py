from __future__ import annotations

import datetime as dt


def _goal_key(goal: dict) -> str:
    return goal.get("goal_id") or goal.get("goal", "")


def _safe_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _reference_day(reference_date: str | None = None) -> dt.date:
    if reference_date:
        parsed = _safe_date(reference_date)
        if parsed:
            return parsed
    return dt.date.today()


def _task_goal_key(task: dict) -> str:
    return task.get("goal_id") or task.get("goal", "")


def _goal_progress_maps(goals: list, history: list, reference_date: str | None = None) -> tuple[dict, dict]:
    ref_day = _reference_day(reference_date)
    valid_goal_keys = {_goal_key(goal) for goal in goals}
    cnt_map = {goal_key: 0 for goal_key in valid_goal_keys}
    last_map: dict[str, str] = {}

    recent7 = history[-7:]
    for record in recent7:
        for task in record.get("tasks", []):
            task_key = _task_goal_key(task)
            if task.get("done") and task_key in cnt_map:
                cnt_map[task_key] += 1

    for record in reversed(history):
        record_day = _safe_date(record.get("date"))
        if record_day and record_day > ref_day:
            continue
        for task in record.get("tasks", []):
            task_key = _task_goal_key(task)
            if task.get("done") and task_key in cnt_map and task_key not in last_map:
                last_map[task_key] = record["date"]
        if len(last_map) == len(valid_goal_keys):
            break

    return cnt_map, last_map


def compute_goal_stats(goals, history):
    cnt_map, last_map = _goal_progress_maps(goals, history)
    sorted_goals = sorted(goals, key=lambda goal: -goal.get("level", 0))
    top_goals = [goal for goal in sorted_goals if goal.get("level", 0) >= 4]
    other_goals = [goal for goal in sorted_goals if goal.get("level", 0) < 4]
    disc_goals = [
        goal
        for goal in goals
        if cnt_map.get(_goal_key(goal), 0) == 0 and bool(history)
    ]
    return cnt_map, last_map, disc_goals, top_goals, other_goals


def compute_goal_staleness(
    goals: list,
    history: list,
    reference_date: str | None = None,
    current_tasks: list | None = None,
) -> list[dict]:
    ref_day = _reference_day(reference_date)
    _, last_map = _goal_progress_maps(goals, history, reference_date=reference_date)
    current_goal_keys = {
        _task_goal_key(task)
        for task in current_tasks or []
        if _task_goal_key(task)
    }

    alerts = []
    for goal in goals:
        goal_key = _goal_key(goal)
        if goal_key in current_goal_keys:
            continue

        last_date = last_map.get(goal_key)
        created_day = _safe_date(goal.get("created")) or ref_day
        last_day = _safe_date(last_date) or created_day
        days_since = max((ref_day - last_day).days, 0)

        deadline_day = _safe_date(goal.get("deadline"))
        days_to_deadline = (deadline_day - ref_day).days if deadline_day else None

        tolerance_days = 2 if goal.get("level", 0) >= 4 else 3
        if days_to_deadline is not None and days_to_deadline <= 7:
            tolerance_days = max(1, tolerance_days - 1)

        if days_since < tolerance_days:
            continue

        if not last_date and days_since == 0:
            continue

        if days_to_deadline is not None and days_to_deadline < 0:
            deadline_note = "已过截止日期"
        elif days_to_deadline is not None:
            deadline_note = f"距截止 {days_to_deadline} 天"
        else:
            deadline_note = ""

        alerts.append(
            {
                "goal": goal.get("goal", ""),
                "goal_id": goal.get("goal_id", ""),
                "level": goal.get("level", 3),
                "last_date": last_date or "尚未推进",
                "days_since": days_since,
                "tolerance_days": tolerance_days,
                "days_to_deadline": days_to_deadline,
                "deadline_note": deadline_note,
                "reason": (
                    f"这条线已经连续 {days_since} 天没有明显推进"
                    + (f"，{deadline_note}" if deadline_note else "")
                ),
            }
        )

    alerts.sort(
        key=lambda item: (
            item["days_to_deadline"] if item["days_to_deadline"] is not None else 9999,
            -item["level"],
            -item["days_since"],
        )
    )
    return alerts
