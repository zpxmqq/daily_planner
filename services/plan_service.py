from __future__ import annotations

import datetime as dt
from collections import Counter

from config.settings import PRIO_LABEL
from data.repository import retrieve_rag_chunks
from services.goal_service import compute_goal_staleness
from services.llm_service import get_embedding_runtime_info
from services.rag_service import format_rag_context
from services.task_context import (
    compute_deviation_signal,
    format_deviation_section,
    goal_key as _goal_key,
    goal_lookup as _goal_lookup,
    is_goal_relevant_today,
    safe_date as _safe_date,
    task_tags as _task_tags,
)


def _recent_history_window(history: list, window_days: int = 7) -> list:
    return history[-window_days:] if history else []


def _records_before_date(history: list, target_date: str | None) -> list:
    if not target_date:
        return history
    return [record for record in history if record.get("date", "") < target_date]


def build_plan_summary(tasks: list) -> str:
    if not tasks:
        return ""

    lines = []
    for task in tasks:
        must_label = "，必须完成" if task.get("must") else ""
        goal_label = f"，目标：{task['goal']}" if task.get("goal") else ""
        tag_label = f"，标签：{task['tag']}" if task.get("tag") else ""
        lines.append(
            f"- [{PRIO_LABEL.get(task.get('priority', 'medium'), '中')}] "
            f"{task.get('text', '')}（{task.get('duration', 30)} 分钟{must_label}{goal_label}{tag_label}）"
        )
    return "\n".join(lines)


def analyze_plan(goals: list, tasks: list, history: list, target_date: str | None = None) -> dict:
    goals_by_id, goals_by_name = _goal_lookup(goals)
    prior_history = _records_before_date(history, target_date)
    total_minutes = sum(int(task.get("duration", 0) or 0) for task in tasks)
    must_minutes = sum(int(task.get("duration", 0) or 0) for task in tasks if task.get("must"))
    high_priority_count = sum(1 for task in tasks if task.get("priority") == "high")
    must_count = sum(1 for task in tasks if task.get("must"))
    unbound_count = sum(1 for task in tasks if not task.get("goal"))

    today_tag_counter = Counter()
    for task in tasks:
        for tag in _task_tags(task, goals_by_id, goals_by_name):
            today_tag_counter[tag] += 1

    recent_tag_counter = Counter()
    for record in _recent_history_window(prior_history, window_days=7):
        for task in record.get("tasks", []):
            if task.get("done"):
                for tag in _task_tags(task, goals_by_id, goals_by_name):
                    recent_tag_counter[tag] += 1

    if total_minutes >= 9 * 60:
        time_assessment = "任务总时长明显偏满，今天更像愿望清单，不像真正能执行完的计划。"
    elif total_minutes >= 7 * 60:
        time_assessment = "任务量偏满，建议减少切换成本，优先守住最重要的 1 到 2 件事。"
    elif total_minutes >= 3 * 60:
        time_assessment = "任务量整体适中，可以重点检查优先级和长期目标覆盖是否合理。"
    else:
        time_assessment = "任务量偏轻，如果今天时间充裕，可以补一项真正推动长期目标的小任务。"

    unbound_task_counter = Counter()
    for record in _recent_history_window(prior_history, window_days=7):
        for task in record.get("tasks", []):
            if not task.get("goal") and task.get("text"):
                unbound_task_counter[task["text"].strip()] += 1
    for task in tasks:
        if not task.get("goal") and task.get("text"):
            unbound_task_counter[task["text"].strip()] += 1

    recurring_unbound = [
        task_name for task_name, count in unbound_task_counter.items() if task_name and count >= 2
    ][:3]

    last_record = prior_history[-1] if prior_history else {}
    previous_suggestion = {
        "date": last_record.get("date", ""),
        "top_priority": last_record.get("top_priority") or last_record.get("ai_plan_result", {}).get("top_priority", ""),
        "tomorrow_suggestion": last_record.get("tomorrow_suggestion") or last_record.get("ai_review_result", {}).get("tomorrow", ""),
        "tracking": last_record.get("suggestion_tracking", {}),
    }

    stale_goal_alerts = compute_goal_staleness(
        goals,
        prior_history,
        reference_date=target_date,
        current_tasks=tasks,
    )[:3]

    return {
        "total_minutes": total_minutes,
        "must_minutes": must_minutes,
        "must_count": must_count,
        "high_priority_count": high_priority_count,
        "unbound_count": unbound_count,
        "overloaded": total_minutes >= 8 * 60 or must_minutes >= 4 * 60 or high_priority_count >= 4,
        "time_assessment": time_assessment,
        "today_tags": dict(today_tag_counter),
        "recent_tag_counts": dict(recent_tag_counter),
        "recurring_unbound_tasks": recurring_unbound,
        "previous_suggestion": previous_suggestion,
        "stale_goal_alerts": stale_goal_alerts,
    }


def build_plan_rag_query(
    goals: list,
    tasks: list,
    profile: dict | None,
    metrics: dict,
    current_status: str = "",
) -> tuple[str, list[str], list[str]]:
    goals_by_id, goals_by_name = _goal_lookup(goals)
    goal_ids = []
    tags = []
    task_lines = []

    for task in tasks:
        if task.get("goal_id"):
            goal_ids.append(task["goal_id"])
        task_tags = _task_tags(task, goals_by_id, goals_by_name)
        tags.extend(task_tags)
        bits = [task.get("text", "").strip()]
        if task.get("goal"):
            bits.append(f"目标：{task['goal']}")
        if task_tags:
            bits.append(f"标签：{', '.join(task_tags)}")
        if task.get("must"):
            bits.append("必须完成")
        if task.get("priority"):
            bits.append(f"优先级：{task['priority']}")
        task_lines.append("；".join(bit for bit in bits if bit))

    previous = metrics.get("previous_suggestion", {})
    previous_tracking = previous.get("tracking", {}) or {}
    query_parts = []
    if profile and profile.get("current_focus"):
        query_parts.append(f"当前阶段重点：{profile['current_focus']}")
    if profile and profile.get("priorities"):
        query_parts.append(f"近期优先事项：{profile['priorities']}")
    if current_status:
        query_parts.append(f"今日状态预估：{current_status}")
    if task_lines:
        query_parts.append("今日任务：" + " | ".join(task_lines))
    if previous.get("top_priority"):
        query_parts.append(f"上一轮晨间重点：{previous['top_priority']}")
    if previous.get("tomorrow_suggestion"):
        query_parts.append(f"上一轮复盘建议：{previous['tomorrow_suggestion']}")
    if previous_tracking.get("status"):
        query_parts.append(
            f"上一轮建议追踪：{previous_tracking.get('status')}；理由：{previous_tracking.get('reason', '')}"
        )
    for alert in metrics.get("stale_goal_alerts", []):
        query_parts.append(f"需要留意：{alert['goal']}，{alert['reason']}")

    ordered_goal_ids = []
    seen_goal_ids = set()
    for goal_id in goal_ids:
        clean = str(goal_id).strip()
        if clean and clean not in seen_goal_ids:
            ordered_goal_ids.append(clean)
            seen_goal_ids.add(clean)

    ordered_tags = []
    seen_tags = set()
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in seen_tags:
            ordered_tags.append(clean)
            seen_tags.add(clean)

    return "\n".join(query_parts), ordered_goal_ids, ordered_tags


def build_plan_context(
    goals,
    tasks,
    history,
    profile=None,
    target_date: str | None = None,
    current_status: str = "",
    return_debug: bool = False,
):
    metrics = analyze_plan(goals, tasks, history, target_date=target_date)
    goals_by_id, goals_by_name = _goal_lookup(goals)

    profile_lines = []
    if profile:
        if profile.get("main_goal"):
            profile_lines.append(f"当前总目标：{profile['main_goal']}")
        if profile.get("current_focus"):
            profile_lines.append(f"当前阶段重点：{profile['current_focus']}")
        if profile.get("priorities"):
            profile_lines.append(f"近期优先事项：{profile['priorities']}")
        if profile.get("constraints"):
            profile_lines.append(f"当前约束：{profile['constraints']}")
        if profile.get("not_urgent"):
            profile_lines.append(f"当前不需要猛冲：{profile['not_urgent']}")

    def goal_line(goal):
        tags = f"；标签：{', '.join(goal.get('tags', []))}" if goal.get("tags") else ""
        deadline = f"；截止：{goal['deadline']}" if goal.get("deadline") else ""
        desc = f"；说明：{goal['description']}" if goal.get("description") else ""
        return f"- {goal['goal']}（重要度 {goal.get('level', 3)}/5{deadline}{tags}{desc}）"

    # P1-2: prioritize goals. Dumping all 50 goals with equal weight dilutes
    # the signal — keep high-importance / near-deadline / today-in-use / stale
    # goals as full lines, and collapse the rest into a one-line bucket. This
    # cuts prompt tokens ~30% on well-populated profiles and lets the model
    # focus on what actually matters this morning.
    if goals:
        today_goal_ids = {str(task.get("goal_id") or "").strip() for task in tasks if task.get("goal_id")}
        today_goal_names = {str(task.get("goal") or "").strip() for task in tasks if task.get("goal")}
        stale_goal_ids = {
            str(alert.get("goal_id") or alert.get("goal") or "").strip()
            for alert in metrics.get("stale_goal_alerts", [])
        }
        reference = _safe_date(target_date) or dt.date.today()

        primary_goals = []
        deferred_goals = []
        for goal in goals:
            if is_goal_relevant_today(
                goal,
                today_goal_ids=today_goal_ids,
                today_goal_names=today_goal_names,
                stale_goal_ids=stale_goal_ids,
                reference_date=reference,
            ):
                primary_goals.append(goal)
            else:
                deferred_goals.append(goal)

        goal_lines = [goal_line(goal) for goal in primary_goals] or ["（无当下需要展开的目标）"]
        if deferred_goals:
            names_preview = "、".join(goal.get("goal", "") for goal in deferred_goals[:5] if goal.get("goal"))
            if len(deferred_goals) > 5:
                names_preview += f"… 等 {len(deferred_goals)} 项"
            goal_lines.append(f"- 其他长期目标（暂不需要重点关注）：{names_preview}")
        goals_text = "\n".join(goal_lines)
    else:
        goals_text = "暂无长期目标"

    def task_line(task):
        must = "，必须完成" if task.get("must") else ""
        goal_name = f"，自动关联目标：{task['goal']}" if task.get("goal") else ""
        tags = _task_tags(task, goals_by_id, goals_by_name)
        tag_text = f"，标签：{', '.join(tags)}" if tags else ""
        return (
            f"- [{PRIO_LABEL.get(task.get('priority', 'medium'), '中')}] "
            f"{task.get('text', '')}（{task.get('duration', 30)} 分钟{must}{goal_name}{tag_text}）"
        )

    tasks_text = "\n".join(task_line(task) for task in tasks) if tasks else "暂无今日任务"

    recent_tags = (
        "；".join(f"{tag}：近 7 天推进 {count} 次" for tag, count in metrics["recent_tag_counts"].items())
        if metrics["recent_tag_counts"]
        else "近 7 天暂无明确标签推进记录"
    )
    today_tags = (
        "；".join(f"{tag}：今日计划 {count} 项" for tag, count in metrics["today_tags"].items())
        if metrics["today_tags"]
        else "今日任务暂未体现明确标签"
    )

    schedule_lines = [
        f"总计划时长：{metrics['total_minutes']} 分钟",
        f"必须完成任务：{metrics['must_count']} 项，共 {metrics['must_minutes']} 分钟",
        f"高优先级任务：{metrics['high_priority_count']} 项",
        f"未自动关联目标任务：{metrics['unbound_count']} 项",
        f"时间判断：{metrics['time_assessment']}",
    ]

    previous_lines = []
    previous = metrics["previous_suggestion"]
    tracking = previous.get("tracking", {})
    if previous.get("top_priority"):
        previous_lines.append(f"上一轮晨间重点：{previous['top_priority']}")
    if previous.get("tomorrow_suggestion"):
        previous_lines.append(f"上一轮复盘建议：{previous['tomorrow_suggestion']}")
    if tracking.get("status"):
        previous_lines.append(f"系统追踪判断：{tracking.get('status')}；理由：{tracking.get('reason', '')}")

    stale_lines = [
        f"- {alert['goal']}：{alert['reason']}"
        for alert in metrics.get("stale_goal_alerts", [])
    ]

    rag_query, rag_goal_ids, rag_tags = build_plan_rag_query(
        goals,
        tasks,
        profile,
        metrics,
        current_status=current_status,
    )
    rag_chunks = retrieve_rag_chunks(
        query_text=rag_query,
        goal_ids=rag_goal_ids,
        tags=rag_tags,
        chunk_types=["plan_chunk", "review_chunk"],
        exclude_date=target_date,
    )

    sections = []
    if profile_lines:
        sections.append("【长期背景档案】\n" + "\n".join(profile_lines))
    if previous_lines:
        sections.append("【上一轮建议追踪】\n" + "\n".join(previous_lines))
    if current_status:
        sections.append(f"【今日状态预估】\n{current_status}")
    if stale_lines:
        sections.append("【需要留意的长期线】\n" + "\n".join(stale_lines))
    if rag_chunks:
        sections.append(format_rag_context(rag_chunks))
    sections.append("【长期目标】\n" + goals_text)
    sections.append("【今日任务】\n" + tasks_text)
    sections.append("【标签推进情况】\n" + f"近期标签推进：{recent_tags}\n今日标签覆盖：{today_tags}")
    sections.append("【计划负荷分析】\n" + "\n".join(schedule_lines))

    if metrics["recurring_unbound_tasks"]:
        recurring_text = "；".join(metrics["recurring_unbound_tasks"])
        sections.append(f"【临时任务提醒】\n这些未关联目标的任务已经连续多次出现：{recurring_text}")

    # Time-analysis 回流：把"近 7 日预估偏差"从复盘移到计划也用一份。
    # Previously only the review prompt saw which tags are systematically
    # under/overestimated. Surfacing it in morning planning lets the model
    # warn before the user commits to yet another 90-minute block on a tag
    # that historically runs 40% over.
    deviation_stats = compute_deviation_signal(history, reference_date=target_date, days=7)
    deviation_section = format_deviation_section(deviation_stats, days=7)
    if deviation_section:
        sections.append(deviation_section)

    context = "\n\n".join(sections)
    if not return_debug:
        return context

    return context, {
        "query_text": rag_query,
        "goal_ids": rag_goal_ids,
        "tags": rag_tags,
        "hits": rag_chunks,
        "embedding": get_embedding_runtime_info(),
    }
