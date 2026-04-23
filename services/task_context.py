"""Shared helpers for plan/review context building.

Previously ``_goal_lookup`` and ``_task_tags`` were duplicated verbatim in
both ``plan_service`` and ``review_service``. Any schema change to task or
goal dicts had to be patched in two places, and P1-2 (context pruning) would
have needed a third. Extracting these into a single module makes future
tweaks land in one place and lets tests cover the mapping logic once.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable


def goal_key(goal: dict) -> str:
    """Canonical identifier for a goal — prefer ``goal_id``, else the name."""
    return goal.get("goal_id") or goal.get("goal", "")


def goal_lookup(goals: Iterable[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build two lookup dicts: by goal_id and by goal name."""
    goals = list(goals)
    by_id = {goal_key(goal): goal for goal in goals}
    by_name = {goal.get("goal", ""): goal for goal in goals if goal.get("goal")}
    return by_id, by_name


def task_tags(
    task: dict,
    goals_by_id: dict[str, dict],
    goals_by_name: dict[str, dict],
) -> list[str]:
    """Ordered, de-duplicated tag list for a task.

    Combines the task's own tag with any tags inherited from the linked goal
    (resolved by ``goal_id`` first, then by name).
    """
    tags: list[str] = []
    if task.get("tag"):
        tags.append(str(task["tag"]).strip())

    linked_goal = None
    if task.get("goal_id") and task["goal_id"] in goals_by_id:
        linked_goal = goals_by_id[task["goal_id"]]
    elif task.get("goal") and task["goal"] in goals_by_name:
        linked_goal = goals_by_name[task["goal"]]

    if linked_goal:
        tags.extend(linked_goal.get("tags", []))

    ordered: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in seen:
            ordered.append(clean)
            seen.add(clean)
    return ordered


def safe_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def is_goal_relevant_today(
    goal: dict,
    today_goal_ids: set[str],
    today_goal_names: set[str],
    stale_goal_ids: set[str],
    reference_date: dt.date | None,
    deadline_window_days: int = 14,
    high_importance_threshold: int = 4,
) -> bool:
    """Decide whether a goal should be rendered in full in the plan prompt.

    Rationale (see P1-2 in plan): 50 goals dumped equally dilutes the signal
    the model actually needs. A goal stays "full" iff it matches any of:
      - importance/level at or above threshold,
      - deadline within the window (now-... window_days out),
      - system flagged it as stale / at risk,
      - today's task list is already working on it.
    Everything else gets folded into a one-line "其他 N 个长期目标" line.
    """
    level = int(goal.get("level", 3) or 0)
    if level >= high_importance_threshold:
        return True

    key = goal_key(goal)
    if key in today_goal_ids:
        return True
    if goal.get("goal", "") in today_goal_names:
        return True
    if key in stale_goal_ids:
        return True

    deadline = safe_date(goal.get("deadline"))
    if deadline and reference_date:
        delta = (deadline - reference_date).days
        if 0 <= delta <= deadline_window_days:
            return True

    return False
