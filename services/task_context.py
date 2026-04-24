"""Shared helpers for plan/review context building.

Previously ``_goal_lookup`` and ``_task_tags`` were duplicated verbatim in
both ``plan_service`` and ``review_service``. Any schema change to task or
goal dicts had to be patched in two places, and P1-2 (context pruning) would
have needed a third. Extracting these into a single module makes future
tweaks land in one place and lets tests cover the mapping logic once.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
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


# ---------------------------------------------------------------------------
# Time-analysis deviation signal
# ---------------------------------------------------------------------------
# Previously only the review pipeline computed this. The planning pipeline
# benefits equally: if "论文" tasks are systematically underestimated by 40%
# across the last week, the morning plan evaluation should warn before the
# user commits to yet another 90-minute writing block.


def compute_deviation_signal(
    history: Iterable[dict],
    reference_date: str | dt.date | None,
    days: int = 7,
) -> dict:
    """Return structured over/underestimation stats over the last N days.

    The result is always a dict with the same keys so callers don't need to
    branch on empty state:

    ``{"count": int, "avg_pct": float, "per_tag": {tag: (avg_pct, n)}}``

    A count of 0 means "no signal available" — callers should skip rendering.
    """
    if isinstance(reference_date, str):
        ref = safe_date(reference_date)
    else:
        ref = reference_date
    if ref is None:
        return {"count": 0, "avg_pct": 0.0, "per_tag": {}}

    window_start = ref - dt.timedelta(days=days)
    per_tag_deltas: dict[str, list[float]] = defaultdict(list)
    total_count = 0
    total_delta_sum = 0.0

    for record in history or []:
        rd = safe_date(record.get("date", ""))
        if not rd or not (window_start <= rd < ref):
            continue
        for task in record.get("tasks", []) or []:
            duration = int(task.get("duration", 0) or 0)
            actual = int(task.get("actual_minutes", 0) or 0)
            if duration <= 0 or actual <= 0:
                continue
            pct = (actual - duration) / duration
            tag = str(task.get("tag") or "未分类").strip() or "未分类"
            per_tag_deltas[tag].append(pct)
            total_count += 1
            total_delta_sum += pct

    if total_count == 0:
        return {"count": 0, "avg_pct": 0.0, "per_tag": {}}

    per_tag = {
        tag: (sum(deltas) / len(deltas), len(deltas))
        for tag, deltas in per_tag_deltas.items()
    }
    return {
        "count": total_count,
        "avg_pct": total_delta_sum / total_count,
        "per_tag": per_tag,
    }


def format_deviation_section(stats: dict, days: int = 7, heading: str | None = None) -> str:
    """Turn ``compute_deviation_signal`` output into a prompt-ready block.

    Returns an empty string when there's nothing worth saying so the caller
    can just ``if section: sections.append(section)``.
    """
    if not stats or stats.get("count", 0) == 0:
        return ""

    lines: list[str] = []
    avg_pct = stats["avg_pct"]
    total_count = stats["count"]
    if avg_pct > 0.10:
        lines.append(f"- 平均每任务高估 {avg_pct * 100:.0f}%（共 {total_count} 条有效记录）")
    elif avg_pct < -0.10:
        lines.append(f"- 平均每任务低估 {-avg_pct * 100:.0f}%（共 {total_count} 条有效记录）")
    else:
        lines.append(f"- 平均偏差较小（±{abs(avg_pct) * 100:.0f}%，共 {total_count} 条记录）")

    for tag, (avg, n) in stats["per_tag"].items():
        if n < 2:
            continue
        if abs(avg) >= 0.3:
            direction = "系统性高估" if avg > 0 else "系统性低估"
            lines.append(f"- '{tag}' 类任务{direction} {abs(avg) * 100:.0f}%（{n} 条）")
        elif abs(avg) <= 0.15:
            lines.append(f"- '{tag}' 类任务实际 vs 预计偏差较小（±{abs(avg) * 100:.0f}%，{n} 条）")

    if not lines:
        return ""
    title = heading or f"【近 {days} 日预估偏差】"
    return f"{title}\n" + "\n".join(lines)
