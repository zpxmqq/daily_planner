import datetime

import streamlit as st

from components.ai_cards import render_ai_plan_card, render_rag_debug_card
from config.settings import PRIO_LABEL
from data.repository import get_record, load_goals, load_history, load_profile, upsert_record
from services.llm_service import generate_plan_feedback
from services.plan_service import analyze_plan, build_plan_context, build_plan_summary
from services.task_inference_service import auto_link_tasks, infer_goal_for_task


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

        for index, task in enumerate(st.session_state.draft_tasks):
            priority = task.get("priority", "medium")
            tag = task.get("tag", "")
            goal = task.get("goal", "")
            goal_source = task.get("goal_source", "")
            priority_badge = (
                f'<span class="badge b-{"high" if priority == "high" else ("mid" if priority == "medium" else "low")}">'
                f"{PRIO_LABEL[priority]}</span>"
            )
            must_badge = '<span class="badge b-alert">必须</span>' if task.get("must") else ""
            goal_badge = f'<span class="badge b-mid">{goal}</span>' if goal else ""
            tag_badge = f'<span class="badge b-mid">#{tag}</span>' if tag else ""
            auto_label = (
                '<span style="font-size:11px;color:#9CA3AF;margin-left:4px">自动识别</span>'
                if goal and goal_source == "auto"
                else ""
            )
            st.markdown(
                f"""
<div class="card" style="padding:12px 16px;margin-bottom:6px">
  <div style="font-size:14px;font-weight:500;color:#1A1D23">{task['text']}</div>
  <div style="margin-top:5px">{priority_badge}{must_badge}{goal_badge}{tag_badge}{auto_label}
    <span style="font-size:11px;color:#9CA3AF;margin-left:4px">约 {task.get('duration', 30)} 分钟</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("删除", key=f"del_t_{index}", help="删除任务"):
                st.session_state.draft_tasks.pop(index)
                st.rerun()

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
                tag = st.text_input("任务标签（可选）", placeholder="例如：英语阅读")
            with col_b:
                duration = st.number_input("预计时长（分钟）", min_value=5, max_value=480, value=30, step=5)
                must = st.checkbox("必须完成")

            submitted = st.form_submit_button("添加", use_container_width=True)
            if submitted and task_text.strip():
                match = infer_goal_for_task(goals, task_text.strip(), tag.strip())
                new_task = {
                    "text": task_text.strip(),
                    "goal": match["goal"] if match else "",
                    "goal_id": match["goal_id"] if match else "",
                    "goal_source": match["source"] if match else "",
                    "priority": priority,
                    "duration": int(duration),
                    "must": must,
                    "tag": tag.strip(),
                    "done": False,
                    "note": "",
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
