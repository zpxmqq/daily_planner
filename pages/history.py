import datetime

import streamlit as st

from config.settings import STATUS_EMOJI
from data.repository import load_goals, load_history
from components.ai_cards import prog_bar
from services.tracking_service import STATUS_COLOR, STATUS_LABEL


def _goal_key(goal: dict) -> str:
    return goal.get("goal_id") or goal.get("goal", "")


def _render_task_list(tasks: list):
    if not tasks:
        st.markdown('<div style="font-size:12px;color:#9CA3AF">无任务记录</div>', unsafe_allow_html=True)
        return

    for task in tasks:
        done = task.get("done", False)
        note = task.get("note", "")
        tag = task.get("tag", "")
        icon = "✓" if done else "○"
        color = "#10B981" if done else "#9CA3AF"
        tag_html = f'<span class="badge b-mid" style="font-size:10px">#{tag}</span>' if tag else ""
        note_html = f'<span style="font-size:11px;color:#6B7280;margin-left:6px">备注：{note}</span>' if note else ""
        st.markdown(
            f'<div style="font-size:13px;color:{color};padding:2px 0">{icon} {task.get("text", "")} {note_html} {tag_html}</div>',
            unsafe_allow_html=True,
        )


def _render_profile_snapshot(snapshot: dict):
    if not snapshot or not any(snapshot.values()):
        return
    rows = [
        ("当前总目标", snapshot.get("main_goal", "")),
        ("当前阶段重点", snapshot.get("current_focus", "")),
        ("近期优先事项", snapshot.get("priorities", "")),
        ("当前约束", snapshot.get("constraints", "")),
        ("当前不需要猛冲", snapshot.get("not_urgent", "")),
    ]
    html = "".join(
        f'<div style="margin-bottom:6px"><span style="font-size:11px;color:#9CA3AF">{label}：</span>'
        f'<span style="font-size:12px;color:#374151">{value}</span></div>'
        for label, value in rows
        if value
    )
    if html:
        st.markdown(
            f'<div style="background:#F9FAFB;border-radius:8px;padding:12px;margin-top:4px">{html}</div>',
            unsafe_allow_html=True,
        )


def page_history():
    st.markdown('<div class="page-title">历史记录</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">查看每天的计划快照、完成质量、AI 结论和建议追踪。</div>', unsafe_allow_html=True)

    history = load_history()
    goals = load_goals()

    if not history:
        st.markdown(
            '<div class="card" style="color:#9CA3AF;text-align:center;padding:48px">暂无历史记录</div>',
            unsafe_allow_html=True,
        )
        return

    recent7 = history[-7:]
    today = datetime.date.today()
    col_left, col_right = st.columns([2, 1], gap="medium")

    with col_left:
        st.markdown('<div class="sec-label">最近 7 天记录</div>', unsafe_allow_html=True)
        for record in reversed(recent7):
            tasks = record.get("tasks", [])
            done_count = sum(1 for task in tasks if task.get("done"))
            total_count = len(tasks)
            pct = int(done_count / total_count * 100) if total_count else 0
            status = record.get("status", "")

            with st.expander(
                f"{record['date']} · {STATUS_EMOJI.get(status, '')} {status or '未记录'} · 完成 {done_count}/{total_count}",
                expanded=False,
            ):
                st.markdown(prog_bar(pct), unsafe_allow_html=True)

                if record.get("plan"):
                    st.markdown('<div style="font-size:11px;font-weight:600;color:#9CA3AF;margin-top:10px">当天计划</div>', unsafe_allow_html=True)
                    st.code(record["plan"], language="text")

                if record.get("profile_snapshot"):
                    st.markdown('<div style="font-size:11px;font-weight:600;color:#9CA3AF;margin-top:10px">当日背景档案</div>', unsafe_allow_html=True)
                    _render_profile_snapshot(record["profile_snapshot"])

                st.markdown('<div style="font-size:11px;font-weight:600;color:#9CA3AF;margin-top:10px">任务明细</div>', unsafe_allow_html=True)
                _render_task_list(tasks)

                if record.get("result"):
                    st.markdown(
                        f'<div style="font-size:12px;color:#6B7280;margin-top:8px"><b>额外完成内容：</b>{record["result"]}</div>',
                        unsafe_allow_html=True,
                    )

                tracking = record.get("suggestion_tracking", {})
                if tracking and tracking.get("status"):
                    track_status = tracking["status"]
                    track_label = STATUS_LABEL.get(track_status, track_status)
                    track_color = STATUS_COLOR.get(track_status, "#9CA3AF")
                    st.markdown('<div style="font-size:11px;font-weight:600;color:#9CA3AF;margin-top:10px">建议追踪</div>', unsafe_allow_html=True)
                    st.markdown(
                        f"""
<div style="background:#F9FAFB;border-left:3px solid {track_color};border-radius:6px;padding:10px 14px;margin-top:4px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
    <span style="font-size:11px;font-weight:600;color:{track_color}">{track_label}</span>
    <span style="font-size:11px;color:#9CA3AF">来自 {tracking.get("source_date", "")} 的建议</span>
  </div>
  <div style="font-size:12px;color:#374151">{tracking.get("reason", "")}</div>
</div>
""",
                        unsafe_allow_html=True,
                    )

                ai_plan = record.get("ai_plan_result", {})
                top_priority = record.get("top_priority") or ai_plan.get("top_priority", "")
                if ai_plan and not ai_plan.get("error"):
                    st.markdown('<div style="font-size:11px;font-weight:600;color:#4B6FD4;margin-top:10px">晨间 AI 评价</div>', unsafe_allow_html=True)
                    if ai_plan.get("overall"):
                        st.markdown(f'<div style="font-size:12px;color:#374151">{ai_plan["overall"]}</div>', unsafe_allow_html=True)
                    for item in ai_plan.get("adjustments", []):
                        st.markdown(f'<div style="font-size:12px;color:#374151">• {item}</div>', unsafe_allow_html=True)
                    if top_priority:
                        st.markdown(f'<div class="ai-highlight" style="margin-top:4px">• 今日重点：{top_priority}</div>', unsafe_allow_html=True)

                ai_review = record.get("ai_review_result", {})
                tomorrow = record.get("tomorrow_suggestion") or ai_review.get("tomorrow", "")
                if ai_review and not ai_review.get("error"):
                    st.markdown('<div style="font-size:11px;font-weight:600;color:#10B981;margin-top:10px">晚间 AI 复盘</div>', unsafe_allow_html=True)
                    if ai_review.get("score"):
                        st.markdown(f'<div style="font-size:12px;color:#374151">{ai_review["score"]}</div>', unsafe_allow_html=True)
                    if ai_review.get("real_progress"):
                        st.markdown(f'<div style="font-size:12px;color:#374151">真正推进：{ai_review["real_progress"]}</div>', unsafe_allow_html=True)
                    if ai_review.get("weak_lines"):
                        st.markdown(f'<div style="font-size:12px;color:#F59E0B">待加强：{ai_review["weak_lines"]}</div>', unsafe_allow_html=True)
                    if tomorrow:
                        st.markdown(f'<div class="ai-highlight" style="margin-top:4px">• 明日建议：{tomorrow}</div>', unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="sec-label">目标推进热度</div>', unsafe_allow_html=True)
        if goals:
            for goal in sorted(goals, key=lambda item: -item.get("level", 0)):
                goal_key = _goal_key(goal)
                count = 0
                for record in recent7:
                    for task in record.get("tasks", []):
                        task_key = task.get("goal_id") or task.get("goal")
                        if task.get("done") and task_key == goal_key:
                            count += 1
                pct = min(count / 7 * 100, 100)
                color = "#10B981" if count >= 4 else ("#4B6FD4" if count >= 2 else "#F59E0B" if count >= 1 else "#E5E7EB")
                status = "稳定" if count >= 4 else ("推进中" if count >= 2 else "断线")
                badge_class = "b-stable" if status == "稳定" else ("b-mid" if status == "推进中" else "b-alert")
                tag_html = "".join(
                    f'<span class="badge b-mid" style="font-size:9px">#{tag}</span>' for tag in goal.get("tags", [])[:2]
                )
                st.markdown(
                    f"""
<div class="card" style="padding:12px 16px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="font-size:13px;font-weight:600;color:#1A1D23;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:110px">{goal['goal']}</div>
    <span class="badge {badge_class}" style="font-size:10px">{status}</span>
  </div>
  <div style="font-size:11px;color:#9CA3AF;margin:3px 0">近 7 天 {count} 次 {tag_html}</div>
  {prog_bar(int(pct), color)}
</div>
""",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="card" style="color:#9CA3AF;font-size:13px">还没有设置长期目标</div>', unsafe_allow_html=True)

        st.markdown('<div class="sec-label" style="margin-top:8px">近 7 天打卡</div>', unsafe_allow_html=True)
        history_by_date = {record["date"]: record for record in history}
        cells = ""
        for offset in range(6, -1, -1):
            day = str(today - datetime.timedelta(days=offset))
            record = history_by_date.get(day)
            has_done = bool(record and any(task.get("done") for task in record.get("tasks", [])))
            cells += f'<span class="heat-cell" style="background:{"#4B6FD4" if has_done else "#E5E7EB"}" title="{day}"></span>'
        st.markdown(f'<div class="card" style="padding:14px">{cells}</div>', unsafe_allow_html=True)
