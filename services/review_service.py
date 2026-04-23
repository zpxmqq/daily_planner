from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from data.repository import retrieve_rag_chunks
from services.goal_service import compute_goal_staleness
from services.llm_service import get_embedding_runtime_info
from services.rag_service import format_rag_context
from services.task_context import goal_lookup as _goal_lookup, task_tags as _task_tags
from services.tracking_service import STATUS_LABEL


def _format_minutes(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes < 60:
        return f"{minutes}min"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours}h"
    return f"{hours}h{rest}min"


def _today_time_usage_section(tasks: list[dict]) -> str:
    """Summarise today's actual vs planned time usage for LLM context."""
    tracked = [
        task
        for task in tasks or []
        if int(task.get("actual_minutes", 0) or 0) > 0
    ]
    if not tracked:
        return ""

    lines = []

    # With a planned duration: compute deviation
    deviations = []
    for task in tracked:
        duration = int(task.get("duration", 0) or 0)
        actual = int(task.get("actual_minutes", 0) or 0)
        if duration <= 0:
            continue
        pct = (actual - duration) / duration
        deviations.append((task, pct, duration, actual))

    if deviations:
        deviations.sort(key=lambda item: item[1], reverse=True)
        most_over = deviations[0]
        most_under = deviations[-1]
        if most_over[1] > 0.2:
            task, pct, duration, actual = most_over
            lines.append(
                f"- 实际用时最多：{task.get('text', '')}（实际 {_format_minutes(actual)}，预计 {_format_minutes(duration)}，超估 {pct * 100:.0f}%）"
            )
        if most_under is not most_over and most_under[1] < -0.2:
            task, pct, duration, actual = most_under
            lines.append(
                f"- 实际用时最少：{task.get('text', '')}（实际 {_format_minutes(actual)}，预计 {_format_minutes(duration)}，低于预计 {-pct * 100:.0f}%）"
            )

    # Unplanned tasks with time record
    unplanned = [task for task in tracked if task.get("unplanned")]
    for task in unplanned[:2]:
        lines.append(
            f"- 未预计但发生：{task.get('text', '')}（{_format_minutes(int(task.get('actual_minutes', 0)))}，标为突发）"
        )

    # Total time tracked
    total_actual = sum(int(task.get("actual_minutes", 0) or 0) for task in tracked)
    total_planned = sum(int(task.get("duration", 0) or 0) for task in tasks or [])
    lines.append(f"- 当天累计实际记录：{_format_minutes(total_actual)}（当天计划总时长 {_format_minutes(total_planned)}）")

    if not lines:
        return ""
    return "【今日时间去向】\n" + "\n".join(lines)


def _recent_deviation_section(history: list[dict], reference_date: str, days: int = 7) -> str:
    """Look across the last N days (excluding today) and summarise bias per tag."""
    try:
        ref = dt.date.fromisoformat(reference_date)
    except (TypeError, ValueError):
        return ""

    window_start = ref - dt.timedelta(days=days)
    per_tag_deltas: dict[str, list[float]] = defaultdict(list)
    total_count = 0
    total_delta_sum = 0.0

    for record in history or []:
        record_date = record.get("date", "")
        try:
            record_date_obj = dt.date.fromisoformat(record_date)
        except ValueError:
            continue
        if not (window_start <= record_date_obj < ref):
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
        return ""

    lines = []
    avg_pct = total_delta_sum / total_count
    if avg_pct > 0.10:
        lines.append(f"- 平均每任务高估 {avg_pct * 100:.0f}%（共 {total_count} 条有效记录）")
    elif avg_pct < -0.10:
        lines.append(f"- 平均每任务低估 {-avg_pct * 100:.0f}%（共 {total_count} 条有效记录）")
    else:
        lines.append(f"- 平均偏差较小（±{abs(avg_pct) * 100:.0f}%，共 {total_count} 条记录）")

    for tag, deltas in per_tag_deltas.items():
        if len(deltas) < 2:
            continue
        avg = sum(deltas) / len(deltas)
        if abs(avg) >= 0.3:
            direction = "系统性高估" if avg > 0 else "系统性低估"
            lines.append(f"- '{tag}' 类任务{direction} {abs(avg) * 100:.0f}%（{len(deltas)} 条）")
        elif abs(avg) <= 0.15:
            lines.append(f"- '{tag}' 类任务实际 vs 预计偏差较小（±{abs(avg) * 100:.0f}%，{len(deltas)} 条）")

    if not lines:
        return ""
    return f"【近 {days} 日预估偏差】\n" + "\n".join(lines)


def build_review_rag_query(
    goals: list,
    tasks: list,
    extra: str,
    profile: dict | None,
    tracking: dict | None,
    stale_goal_alerts: list[dict] | None = None,
) -> tuple[str, list[str], list[str]]:
    goals_by_id, goals_by_name = _goal_lookup(goals)
    goal_ids = []
    tags = []
    done_lines = []
    undone_lines = []

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
        if task.get("note"):
            bits.append(f"备注：{task['note']}")
        line = "；".join(bit for bit in bits if bit)
        if task.get("done"):
            done_lines.append(line)
        else:
            undone_lines.append(line)

    query_parts = []
    if profile and profile.get("current_focus"):
        query_parts.append(f"当前阶段重点：{profile['current_focus']}")
    if done_lines:
        query_parts.append("今日已完成：" + " | ".join(done_lines))
    if undone_lines:
        query_parts.append("今日未完成：" + " | ".join(undone_lines))
    if extra:
        query_parts.append(f"额外完成内容：{extra}")
    if tracking and tracking.get("status"):
        query_parts.append(
            f"昨日建议追踪：{tracking['status']}；来源重点：{tracking.get('source_top_priority', '')}；来源建议：{tracking.get('source_tomorrow', '')}；理由：{tracking.get('reason', '')}"
        )
    for alert in stale_goal_alerts or []:
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


def build_review_context(
    goals,
    today_rec,
    done_list,
    undone_list,
    extra,
    status,
    profile=None,
    done_notes=None,
    tracking=None,
    history=None,
    return_debug: bool = False,
):
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
        return f"- {goal['goal']}（重要度 {goal.get('level', 3)}/5{tags}）"

    goals_text = "\n".join(goal_line(goal) for goal in goals) if goals else "暂无长期目标"

    plan_text = today_rec.get("plan", "") if today_rec else ""
    tasks = today_rec.get("tasks", []) if today_rec else []

    note_map = done_notes or {}
    if done_list:
        done_lines = []
        for task_name in done_list:
            note = note_map.get(task_name, "")
            done_lines.append(f"- {task_name}" + (f"（备注：{note}）" if note else ""))
        done_text = "\n".join(done_lines)
    else:
        done_text = "无"

    tag_counter = Counter()
    for task in tasks:
        if task.get("done"):
            for tag in _task_tags(task, goals_by_id, goals_by_name):
                tag_counter[tag] += 1
    tag_summary = (
        "；".join(f"{tag}：今天推进 {count} 次" for tag, count in tag_counter.items())
        if tag_counter
        else "今天没有形成明显的标签推进"
    )

    tracking_text = ""
    if tracking and tracking.get("status"):
        tracking_text = (
            f"追踪状态：{STATUS_LABEL.get(tracking['status'], tracking['status'])}\n"
            f"昨日晨间重点：{tracking.get('source_top_priority', '')}\n"
            f"昨日复盘建议：{tracking.get('source_tomorrow', '')}\n"
            f"系统判断理由：{tracking.get('reason', '')}"
        )

    stale_goal_alerts = compute_goal_staleness(
        goals,
        history or [],
        reference_date=today_rec.get("date") if today_rec else None,
        current_tasks=tasks,
    )[:3]

    rag_query, rag_goal_ids, rag_tags = build_review_rag_query(
        goals,
        tasks,
        extra,
        profile,
        tracking,
        stale_goal_alerts=stale_goal_alerts,
    )
    rag_chunks = retrieve_rag_chunks(
        query_text=rag_query,
        goal_ids=rag_goal_ids,
        tags=rag_tags,
        chunk_types=["review_chunk", "plan_chunk"],
        exclude_date=today_rec.get("date") if today_rec else None,
    )

    sections = []
    if profile_lines:
        sections.append("【长期背景档案】\n" + "\n".join(profile_lines))
    sections.append("【长期目标】\n" + goals_text)
    if stale_goal_alerts:
        sections.append(
            "【需要留意的长期线】\n"
            + "\n".join(f"- {alert['goal']}：{alert['reason']}" for alert in stale_goal_alerts)
        )
    if tracking_text:
        sections.append("【昨日建议追踪】\n" + tracking_text)
    if rag_chunks:
        sections.append(format_rag_context(rag_chunks))

    today_time_section = _today_time_usage_section(tasks)
    if today_time_section:
        sections.append(today_time_section)

    recent_section = _recent_deviation_section(
        history or [],
        reference_date=today_rec.get("date") if today_rec else "",
    )
    if recent_section:
        sections.append(recent_section)

    sections.append(
        "【今日复盘输入】\n"
        f"今日计划：{plan_text or '未单独生成文字计划，以下以任务清单为准'}\n\n"
        f"已完成：\n{done_text}\n\n"
        f"未完成：{', '.join(undone_list) or '无'}\n"
        f"额外完成内容：{extra or '无'}\n"
        f"今日状态：{status}\n"
        f"标签推进概览：{tag_summary}"
    )
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
