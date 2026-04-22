import datetime

import streamlit as st

from components.ai_cards import render_ai_review_card, render_rag_debug_card, render_suggestion_tracking_card
from config.settings import TODAY
from data.repository import get_record, load_goals, load_history, load_profile, upsert_record
from services.llm_service import generate_review_feedback
from services.review_service import build_review_context
from services.tracking_service import auto_track_suggestion


STATUS_OPTIONS = {
    "顺利": "😊 顺利",
    "一般": "😐 一般",
    "很累": "😫 很累",
}


def page_review():
    _, center_col, _ = st.columns([1, 3, 1])
    with center_col:
        st.markdown('<div class="page-title">晚间复盘</div>', unsafe_allow_html=True)
        st.markdown('<div class="page-sub">保持轻量，只记录最关键的完成情况、备注和今天状态。</div>', unsafe_allow_html=True)

        today_record = get_record(TODAY)
        tasks = today_record.get("tasks", []) if today_record else []
        goals = load_goals()
        history = load_history()
        profile = load_profile()

        if not st.session_state.get("tracking_result") and today_record and today_record.get("suggestion_tracking"):
            st.session_state.tracking_result = today_record["suggestion_tracking"]
        if not st.session_state.get("review_ai_result") and today_record and today_record.get("ai_review_result"):
            st.session_state.review_ai_result = today_record["ai_review_result"]
        if "review_status_value" not in st.session_state:
            st.session_state.review_status_value = today_record.get("status", "一般") if today_record else "一般"
        elif today_record and today_record.get("status") and st.session_state.review_status_value != today_record.get("status"):
            st.session_state.review_status_value = today_record.get("status")
        if not today_record:
            st.session_state.review_ai_result = None
            st.session_state.tracking_result = None
            st.session_state.review_rag_debug = None
            st.session_state.review_status_value = "一般"

        updated_tasks = []
        if tasks:
            st.markdown('<div class="sec-label">今日任务</div>', unsafe_allow_html=True)
            st.caption("实际用时若未用计时器记录，可在此手填；供 AI 做专注度分析。")
            for index, task in enumerate(tasks):
                done = st.checkbox(task["text"], value=task.get("done", False), key=f"rv_t_{index}")
                note_col, actual_col = st.columns([3, 1])
                with note_col:
                    note = st.text_input(
                        f"note_{index}",
                        value=task.get("note", ""),
                        placeholder="一句短备注（可选）",
                        label_visibility="collapsed",
                        key=f"rv_note_{index}",
                    )
                with actual_col:
                    actual_minutes = st.number_input(
                        "实际用时",
                        min_value=0,
                        max_value=600,
                        value=int(task.get("actual_minutes", 0) or 0),
                        step=5,
                        key=f"rv_actual_{index}",
                        label_visibility="collapsed",
                        help=f"预计 {task.get('duration', 0)} 分钟",
                    )
                updated_tasks.append(
                    {
                        **task,
                        "done": done,
                        "note": note.strip(),
                        "actual_minutes": int(actual_minutes or 0),
                    }
                )
        else:
            st.markdown(
                '<div class="card" style="color:#9CA3AF;font-size:13px;text-align:center;padding:18px">今天还没有晨间计划，也可以直接补充完成内容。</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="sec-label" style="margin-top:8px">额外完成内容（可选）</div>', unsafe_allow_html=True)
        extra = st.text_area(
            "extra",
            label_visibility="collapsed",
            placeholder="记录计划外完成的事情，或者今天值得补充的一点进展。",
            height=80,
            key="rv_extra",
        )

        st.markdown('<div class="sec-label">今日状态</div>', unsafe_allow_html=True)
        st.radio(
            "status",
            list(STATUS_OPTIONS.keys()),
            format_func=lambda key: STATUS_OPTIONS[key],
            horizontal=True,
            label_visibility="collapsed",
            key="review_status_value",
        )
        status_value = st.session_state.review_status_value

        if st.button("生成复盘总结", use_container_width=True, key="gen_review"):
            if updated_tasks:
                upsert_record(date=TODAY, tasks=updated_tasks, result=extra, status=status_value)
            else:
                upsert_record(date=TODAY, result=extra, status=status_value)

            yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
            yesterday_record = get_record(yesterday)
            tracking = auto_track_suggestion(yesterday_record, updated_tasks, extra)
            if tracking:
                upsert_record(date=TODAY, suggestion_tracking=tracking)
                st.session_state.tracking_result = tracking

            done_tasks = [task for task in updated_tasks if task.get("done")]
            undone_list = [task["text"] for task in updated_tasks if not task.get("done")]
            done_list = [task["text"] for task in done_tasks]
            done_notes = {task["text"]: task.get("note", "") for task in done_tasks if task.get("note")}
            today_snapshot = {**(today_record or {}), "tasks": updated_tasks}
            user_content, rag_debug = build_review_context(
                goals,
                today_snapshot,
                done_list,
                undone_list,
                extra,
                status_value,
                profile=profile,
                done_notes=done_notes,
                tracking=tracking,
                history=history,
                return_debug=True,
            )
            st.session_state.review_rag_debug = rag_debug

            with st.spinner("AI 正在生成复盘总结..."):
                data = generate_review_feedback(
                    user_content,
                    feedback_style=profile.get("feedback_style", "rational"),
                )

            upsert_record(
                date=TODAY,
                tasks=updated_tasks,
                ai_review_result=data,
                profile_snapshot=profile,
                tomorrow_suggestion=data.get("tomorrow", ""),
            )
            st.session_state.review_ai_result = data
            st.rerun()

        tracking_result = st.session_state.get("tracking_result")
        if tracking_result:
            render_suggestion_tracking_card(tracking_result, date=TODAY)

        style_label = {
            "gentle": "温和型",
            "rational": "理性型",
            "strict": "严格型",
        }.get(profile.get("feedback_style", "rational"), "理性型")
        st.caption(f"当前反馈风格：{style_label}")
        if st.session_state.review_ai_result:
            render_ai_review_card(st.session_state.review_ai_result)
        render_rag_debug_card(st.session_state.get("review_rag_debug"), title="复盘页 RAG 检索命中")
