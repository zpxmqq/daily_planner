import datetime

import streamlit as st

from components.ai_cards import prog_bar, render_tracking_summary_card
from config.settings import STATUS_EMOJI, WEEKDAYS
from data.repository import load_goals, load_history, load_profile
from services.dashboard_service import build_dashboard_snapshot


def _goto(page: str):
    st.session_state.page = page
    st.rerun()


def _render_recent_summary(recent_records: list):
    st.markdown('<div class="sec-label">最近 3 天</div>', unsafe_allow_html=True)
    if not recent_records:
        st.markdown(
            '<div class="card" style="color:#9CA3AF;font-size:13px">还没有历史记录，先从今天的计划开始。</div>',
            unsafe_allow_html=True,
        )
        return

    for record in reversed(recent_records):
        tasks = record.get("tasks", [])
        done_count = sum(1 for task in tasks if task.get("done"))
        total_count = len(tasks)
        pct = int(done_count / total_count * 100) if total_count else 0
        status = record.get("status", "")
        tomorrow = record.get("tomorrow_suggestion") or record.get("ai_review_result", {}).get("tomorrow", "")
        st.markdown(
            f"""
<div class="card" style="padding:14px 18px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <span style="font-size:13px;font-weight:600;color:#1A1D23">{record['date']}</span>
    <span style="font-size:13px">{STATUS_EMOJI.get(status, "")} {status or '未复盘'}</span>
  </div>
  <div style="font-size:12px;color:#9CA3AF;margin-top:4px">完成 {done_count}/{total_count} 个任务</div>
  {prog_bar(pct)}
  {"" if not tomorrow else f'<div style="font-size:12px;color:#374151;margin-top:8px">明日建议：{tomorrow}</div>'}
</div>
""",
            unsafe_allow_html=True,
        )


def page_dashboard():
    goals = load_goals()
    history = load_history()
    profile = load_profile()
    snapshot = build_dashboard_snapshot(goals, history, profile)

    toolbar_col, _ = st.columns([1, 7])
    with toolbar_col:
        if st.button("个人信息", key="dashboard_to_personal_small"):
            _goto("personal")

    weekday = WEEKDAYS[datetime.date.today().weekday()]
    date_str = datetime.date.today().strftime(f"%Y年%m月%d日 {weekday}")
    hour = datetime.datetime.now().hour
    greeting = (
        "早上好，新的一天从清楚的计划开始。"
        if hour < 12
        else "下午好，先守住今天最重要的一件事。"
        if hour < 18
        else "晚上好，适合把今天收成一个完整闭环。"
    )

    st.markdown(
        f"""
<div class="card" style="margin-bottom:20px">
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:4px">{date_str}</div>
  <div style="font-size:20px;font-weight:700;color:#1A1D23">{greeting}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([3, 2], gap="medium")

    with left_col:
        if snapshot["primary_mode"] == "tomorrow":
            section_title = "明天先做什么"
        elif snapshot["primary_mode"] == "top_priority":
            section_title = "今天最重要的一件事"
        else:
            section_title = "先定下今天重点"

        st.markdown(
            f"""
<div class="card card-blue" style="padding:18px 20px">
  <div style="font-size:12px;font-weight:700;color:#4B6FD4;text-transform:uppercase;letter-spacing:.06em">{section_title}</div>
  <div class="ai-highlight" style="margin-top:10px;font-size:14px;font-weight:600">{snapshot['primary_text']}</div>
  <div style="font-size:12px;color:#6B7280;margin-top:10px">{snapshot['primary_caption']}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        btn_left, btn_right = st.columns(2)
        with btn_left:
            if st.button("今日计划", use_container_width=True, key="dashboard_to_plan"):
                _goto("plan")
        with btn_right:
            if st.button("晚间复盘", use_container_width=True, key="dashboard_to_review"):
                _goto("review")

        if snapshot["workflow_state"] == "empty":
            st.info("今天还没有保存任务，先去计划页定下 1 到 3 个真正要推进的任务。")
        elif snapshot["workflow_state"] == "planned":
            st.info("计划已经保存。先执行最重要的一件事，晚一点再回来做轻量复盘。")
        else:
            st.success("今天已经完成复盘，明天可以沿着这条建议直接开局。")

        _render_recent_summary(snapshot["recent_records"])

    with right_col:
        st.caption("目标和档案已经收纳到左上角的“个人信息”里，需要时再进去调整。")
        render_tracking_summary_card(snapshot["latest_tracking"])
