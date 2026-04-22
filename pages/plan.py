import datetime
import time

import streamlit as st

from components.ai_cards import render_ai_plan_card, render_rag_debug_card
from config.settings import PRIO_LABEL
from data.repository import get_record, load_goals, load_history, load_profile, upsert_record
from services.classification_service import classify_task_tag
from services.llm_service import generate_plan_feedback
from services.plan_service import analyze_plan, build_plan_context, build_plan_summary
from services.task_inference_service import auto_link_tasks, infer_goal_for_task
from services.time_tracking_service import (
    aggregate_actual_minutes,
    get_active_session,
    recover_orphan_sessions,
    resolve_orphan_session,
    start_session,
    stop_session,
)


STATUS_OPTIONS = {
    "顺利": "😊 顺利",
    "一般": "😐 一般",
    "很累": "😫 很累",
}


def _normalize_draft_tasks(goals: list):
    current_tasks = st.session_state.get("draft_tasks", [])
    linked_tasks = auto_link_tasks(goals, current_tasks, keep_existing=True)
    if linked_tasks != current_tasks:
        st.session_state.draft_tasks = linked_tasks


def _load_plan_state_for_date(date_str: str, goals: list):
    if st.session_state.get("draft_tasks_date") == date_str:
        _normalize_draft_tasks(goals)
        return

    record = get_record(date_str)
    tasks = list(record.get("tasks", [])) if record else []
    st.session_state.draft_tasks = auto_link_tasks(goals, tasks, keep_existing=True)
    st.session_state.plan_ai_result = record.get("ai_plan_result") if record else None
    st.session_state.plan_rag_debug = None
    st.session_state.plan_status_value = (record or {}).get("status") or "一般"
    st.session_state.draft_tasks_date = date_str
    # 若该日已有 AI 计划结果，视为已确认；新加任务默认标记为突发
    st.session_state.plan_confirmed_at = (
        datetime.datetime.now().isoformat(timespec="seconds")
        if record and record.get("ai_plan_result")
        else None
    )


AUTO_SOURCE_LABEL = {
    "manual": ("手填", "#4B6FD4"),
    "keyword": ("关键词识别", "#3B82F6"),
    "embedding": ("语义匹配", "#8B5CF6"),
    "unplanned": ("突发", "#F59E0B"),
    "fallback": ("兜底分类", "#9CA3AF"),
}


def _format_elapsed(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _sync_actual_minutes(date_str: str, task_key: str):
    """Recompute the task's ``actual_minutes`` from sessions and persist."""
    minutes = aggregate_actual_minutes(date_str, task_key)
    tasks = st.session_state.get("draft_tasks", [])
    for task in tasks:
        if task.get("text") == task_key:
            task["actual_minutes"] = minutes
            break
    upsert_record(date=date_str, tasks=tasks)


def _render_orphan_recovery(date_str: str):
    orphans = recover_orphan_sessions()
    if not orphans:
        return
    st.markdown(
        '<div class="card" style="border-left:4px solid #F59E0B;padding:14px 16px;margin-bottom:8px">'
        '<div style="font-size:12px;font-weight:700;color:#92400E;text-transform:uppercase;letter-spacing:.04em">'
        '检测到未正常结束的专注记录</div>'
        '<div style="font-size:12px;color:#78350F;margin-top:4px">'
        '可能是上次浏览器意外关闭。请填入大致的实际用时（分钟），系统会把它写回任务。</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    now = datetime.datetime.now()
    for session in orphans:
        started = session.get("started_at", "")
        try:
            started_dt = datetime.datetime.fromisoformat(started)
            default_minutes = max(int((now - started_dt).total_seconds() // 60), 1)
            started_display = started_dt.strftime("%m-%d %H:%M")
        except ValueError:
            default_minutes = 0
            started_display = started or "—"
        cols = st.columns([3, 1, 1])
        with cols[0]:
            st.markdown(
                f"<div style=\"font-size:13px;color:#374151\">任务：<b>{session.get('task_key', '') or '未知任务'}</b>"
                f"（开始时间 {started_display}，日期 {session.get('record_date', '')}）</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            minutes_value = st.number_input(
                "实际用时（分钟）",
                min_value=0,
                max_value=600,
                value=default_minutes,
                step=5,
                key=f"orphan_min_{session['session_id']}",
                label_visibility="collapsed",
            )
        with cols[2]:
            if st.button("保存", key=f"orphan_save_{session['session_id']}", use_container_width=True):
                resolve_orphan_session(session["session_id"], minutes_value)
                if session.get("record_date") == date_str and session.get("task_key"):
                    _sync_actual_minutes(date_str, session["task_key"])
                st.success("已记录实际用时")
                st.rerun()


def _render_timer_row(date_str: str, task: dict, task_index: int):
    task_key = task.get("text", "")
    if not task_key:
        return

    active = get_active_session(date_str, task_key)
    cols = st.columns([3, 1, 1])

    if active:
        try:
            started_at = datetime.datetime.fromisoformat(active["started_at"]).timestamp()
        except ValueError:
            started_at = time.time()
        elapsed = int(time.time() - started_at)
        with cols[0]:
            st.markdown(
                f"<div style=\"font-size:12px;color:#DC2626\">🔴 正在专注记录 · {_format_elapsed(elapsed)}</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            if st.button("⏹ 结束", key=f"stop_t_{task_index}", help="结束本段专注", use_container_width=True):
                stop_session(active["session_id"])
                _sync_actual_minutes(date_str, task_key)
                st.rerun()
        with cols[2]:
            if st.button("🗑 删除任务", key=f"del_t_{task_index}", use_container_width=True):
                stop_session(active["session_id"])
                st.session_state.draft_tasks.pop(task_index)
                st.rerun()
    else:
        with cols[0]:
            actual_minutes = int(task.get("actual_minutes", 0) or 0)
            if actual_minutes > 0:
                st.markdown(
                    f"<div style=\"font-size:12px;color:#6B7280\">已记录实际用时 · <b>{actual_minutes}</b> 分钟</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="font-size:12px;color:#9CA3AF">尚未记录实际用时（可选，用于 AI 专注度分析）</div>',
                    unsafe_allow_html=True,
                )
        with cols[1]:
            if st.button(
                "▶️ 开始",
                key=f"start_t_{task_index}",
                help="开始记录实际用时，供 AI 做专注度分析",
                use_container_width=True,
            ):
                start_session(date_str, task_key)
                st.rerun()
        with cols[2]:
            if st.button("🗑 删除", key=f"del_t_{task_index}", use_container_width=True):
                st.session_state.draft_tasks.pop(task_index)
                st.rerun()


def _render_plan_metrics(metrics: dict):
    stale_goal_alerts = metrics.get("stale_goal_alerts", [])
    stale_line = (
        "；".join(f"{item['goal']}（已停滞 {item['days_since']} 天）" for item in stale_goal_alerts)
        if stale_goal_alerts
        else "最近没有需要额外提醒的长期线"
    )
    st.markdown(
        f"""
<div class="card" style="padding:14px 16px;margin-bottom:8px">
  <div style="font-size:12px;font-weight:700;color:#6B7280;text-transform:uppercase;letter-spacing:.04em">计划负荷分析</div>
  <div style="font-size:13px;color:#374151;margin-top:8px">总时长：{metrics['total_minutes']} 分钟</div>
  <div style="font-size:13px;color:#374151;margin-top:4px">必须完成：{metrics['must_count']} 项</div>
  <div style="font-size:13px;color:#374151;margin-top:4px">高优先级：{metrics['high_priority_count']} 项</div>
  <div style="font-size:13px;color:#374151;margin-top:4px">未自动关联目标：{metrics['unbound_count']} 项</div>
  <div style="font-size:13px;color:#4B5563;margin-top:8px">{metrics['time_assessment']}</div>
  <div style="font-size:12px;color:#9CA3AF;margin-top:8px">{stale_line}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def page_plan():
    st.markdown('<div class="page-title">今日计划</div>', unsafe_allow_html=True)

    selected_date = st.date_input("日期", value=datetime.date.today(), key="plan_date")
    date_str = str(selected_date)

    goals = load_goals()
    history = load_history()
    profile = load_profile()
    _load_plan_state_for_date(date_str, goals)

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.markdown('<div class="sec-label">任务列表</div>', unsafe_allow_html=True)

        _render_orphan_recovery(date_str)

        for index, task in enumerate(st.session_state.draft_tasks):
            priority = task.get("priority", "medium")
            tag = task.get("tag", "")
            goal = task.get("goal", "")
            goal_source = task.get("goal_source", "")
            auto_tag_source = task.get("auto_tag_source", "")
            priority_badge = (
                f'<span class="badge b-{"high" if priority == "high" else ("mid" if priority == "medium" else "low")}">'
                f"{PRIO_LABEL[priority]}</span>"
            )
            must_badge = '<span class="badge b-alert">必须</span>' if task.get("must") else ""
            unplanned_badge = (
                '<span class="badge" style="background:#FEF3C7;color:#92400E">突发</span>'
                if task.get("unplanned")
                else ""
            )
            goal_badge = f'<span class="badge b-mid">{goal}</span>' if goal else ""
            if tag:
                source_info = AUTO_SOURCE_LABEL.get(auto_tag_source, ("", ""))
                tag_color = source_info[1] if source_info[1] else "#6B7280"
                tag_badge = (
                    f'<span class="badge" style="background:{tag_color}22;color:{tag_color};'
                    f'border:1px solid {tag_color}55" title="{source_info[0] or "标签"}">#{tag}</span>'
                )
            else:
                tag_badge = ""
            auto_goal_label = (
                '<span style="font-size:11px;color:#9CA3AF;margin-left:4px">自动识别目标</span>'
                if goal and goal_source == "auto"
                else ""
            )
            auto_tag_hint = (
                f'<span style="font-size:11px;color:#9CA3AF;margin-left:4px">{AUTO_SOURCE_LABEL.get(auto_tag_source, ("", ""))[0]}</span>'
                if auto_tag_source and auto_tag_source != "manual"
                else ""
            )
            st.markdown(
                f"""
<div class="card" style="padding:12px 16px;margin-bottom:6px">
  <div style="font-size:14px;font-weight:500;color:#1A1D23">{task['text']}</div>
  <div style="margin-top:5px">{priority_badge}{must_badge}{unplanned_badge}{goal_badge}{tag_badge}{auto_goal_label}{auto_tag_hint}
    <span style="font-size:11px;color:#9CA3AF;margin-left:4px">约 {task.get('duration', 30)} 分钟</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            _render_timer_row(date_str, task, index)

        metrics = analyze_plan(goals, st.session_state.draft_tasks, history, target_date=date_str)
        if st.session_state.draft_tasks:
            _render_plan_metrics(metrics)
            if metrics["recurring_unbound_tasks"]:
                st.info(
                    "这些未自动关联目标的任务最近反复出现："
                    + "；".join(metrics["recurring_unbound_tasks"])
                    + "。如果它们会持续出现，可以考虑纳入长期目标体系。"
                )

        st.markdown('<div class="sec-label" style="margin-top:8px">今日状态预估</div>', unsafe_allow_html=True)
        st.radio(
            "今日状态预估",
            list(STATUS_OPTIONS.keys()),
            format_func=lambda key: STATUS_OPTIONS[key],
            horizontal=True,
            label_visibility="collapsed",
            key="plan_status_value",
        )

        st.markdown('<div class="sec-label" style="margin-top:8px">添加任务</div>', unsafe_allow_html=True)
        st.caption("直接自然输入任务即可，系统会自动识别最可能关联的长期目标。")
        with st.form("add_task", clear_on_submit=True):
            task_text = st.text_input("任务描述", placeholder="今天要完成什么？")
            col_a, col_b = st.columns(2)
            with col_a:
                priority = st.selectbox("优先级", list(PRIO_LABEL.keys()), format_func=lambda key: PRIO_LABEL[key])
                tag = st.text_input("任务标签（可选）", placeholder="留空将自动识别")
            with col_b:
                duration = st.number_input("预计时长（分钟）", min_value=5, max_value=480, value=30, step=5)
                must = st.checkbox("必须完成")
                unplanned_flag = st.checkbox("临时/突发", help="勾选后该任务标记为计划外突发任务")

            submitted = st.form_submit_button("添加", use_container_width=True)
            if submitted and task_text.strip():
                task_text_clean = task_text.strip()
                tag_clean = tag.strip()

                # 若晨评已经出过一次，之后新加的任务默认视作突发
                is_unplanned = bool(unplanned_flag) or bool(st.session_state.get("plan_confirmed_at"))

                match = infer_goal_for_task(goals, task_text_clean, tag_clean)

                # 历史任务：取最近 30 天的历史（不含空文本）用于 embedding 聚类
                historical_tasks = []
                for record in history[-60:]:
                    for hist_task in record.get("tasks", []) or []:
                        if hist_task.get("text") and hist_task.get("tag"):
                            historical_tasks.append(hist_task)

                # 已知 tag 白名单：目标 tags ∪ 历史出现过的 tags
                known_tags_set = set()
                for goal_item in goals:
                    known_tags_set.update(str(t).strip() for t in goal_item.get("tags", []) if str(t).strip())
                for hist_task in historical_tasks:
                    if hist_task.get("tag"):
                        known_tags_set.add(str(hist_task["tag"]).strip())
                known_tags = sorted(known_tags_set)

                classification = classify_task_tag(
                    task_text=task_text_clean,
                    user_tag=tag_clean,
                    historical_tasks=historical_tasks,
                    known_tags=known_tags,
                    is_unplanned=is_unplanned,
                )

                new_task = {
                    "text": task_text_clean,
                    "goal": match["goal"] if match else "",
                    "goal_id": match["goal_id"] if match else "",
                    "goal_source": match["source"] if match else "",
                    "priority": priority,
                    "duration": int(duration),
                    "must": must,
                    "tag": classification.get("tag", tag_clean),
                    "done": False,
                    "note": "",
                    "actual_minutes": 0,
                    "auto_tag_source": classification.get("auto_source", ""),
                    "unplanned": bool(is_unplanned),
                }
                st.session_state.draft_tasks.append(new_task)
                st.rerun()

        if st.session_state.draft_tasks:
            if st.button("保存并获取 AI 评价", use_container_width=True, key="submit_plan"):
                st.session_state.draft_tasks = auto_link_tasks(goals, st.session_state.draft_tasks, keep_existing=True)
                metrics = analyze_plan(goals, st.session_state.draft_tasks, history, target_date=date_str)
                plan_summary = build_plan_summary(st.session_state.draft_tasks)
                upsert_record(
                    date=date_str,
                    tasks=st.session_state.draft_tasks,
                    plan=plan_summary,
                    status=st.session_state.plan_status_value,
                    profile_snapshot=profile,
                    plan_metrics=metrics,
                )
                user_content, rag_debug = build_plan_context(
                    goals,
                    st.session_state.draft_tasks,
                    history,
                    profile=profile,
                    target_date=date_str,
                    current_status=st.session_state.plan_status_value,
                    return_debug=True,
                )
                st.session_state.plan_rag_debug = rag_debug
                with st.spinner("AI 正在评估今日计划..."):
                    data = generate_plan_feedback(
                        user_content,
                        feedback_style=profile.get("feedback_style", "rational"),
                    )
                upsert_record(
                    date=date_str,
                    tasks=st.session_state.draft_tasks,
                    ai_plan_result=data,
                    top_priority=data.get("top_priority", ""),
                    plan_metrics=metrics,
                )
                st.session_state.plan_ai_result = data
                st.session_state.plan_confirmed_at = datetime.datetime.now().isoformat(timespec="seconds")
                st.rerun()

    with col_right:
        st.markdown('<div class="sec-label">AI 计划评价</div>', unsafe_allow_html=True)
        style_label = {
            "gentle": "温和型",
            "rational": "理性型",
            "strict": "严格型",
        }.get(profile.get("feedback_style", "rational"), "理性型")
        st.caption(f"当前反馈风格：{style_label}")
        if st.session_state.plan_ai_result:
            render_ai_plan_card(st.session_state.plan_ai_result)
        else:
            st.markdown(
                """
<div class="card" style="text-align:center;padding:48px 20px;color:#9CA3AF">
  <div style="font-size:14px;font-weight:500">添加任务后点击“保存并获取 AI 评价”</div>
  <div style="font-size:12px;margin-top:6px">AI 会结合长期背景、自动识别的目标推进和历史经验给出建议。</div>
</div>
""",
                unsafe_allow_html=True,
            )
        render_rag_debug_card(st.session_state.get("plan_rag_debug"), title="计划页 RAG 检索命中")
