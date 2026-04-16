from __future__ import annotations

from collections import Counter

from data.repository import retrieve_rag_chunks
from services.goal_service import compute_goal_staleness
from services.llm_service import get_embedding_runtime_info
from services.rag_service import format_rag_context
from services.tracking_service import STATUS_LABEL


def _goal_lookup(goals: list) -> tuple[dict[str, dict], dict[str, dict]]:
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
