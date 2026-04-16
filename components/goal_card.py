import datetime

import streamlit as st

from data.repository import save_goals, sync_goal_history


def _goal_key(goal: dict) -> str:
    return goal.get("goal_id") or goal.get("goal", "")


def _tag_badges(tags: list) -> str:
    if not tags:
        return ""
    return "".join(
        f'<span class="badge b-mid" style="font-size:10px;margin-right:3px"># {tag}</span>'
        for tag in tags
    )


def _render_edit_form(goal: dict, goals: list):
    goal_id = _goal_key(goal)
    old_name = goal.get("goal", "")
    with st.form(key=f"edit_form_{goal_id}"):
        st.markdown(
            '<div style="font-size:12px;font-weight:600;color:#4B6FD4;margin-bottom:8px">编辑目标</div>',
            unsafe_allow_html=True,
        )
        new_name = st.text_input("目标名称", value=goal.get("goal", ""))
        new_desc = st.text_input(
            "描述（可选）",
            value=goal.get("description", ""),
            placeholder="一句话说明这个目标",
        )

        col_left, col_right = st.columns(2)
        with col_left:
            deadline_value = None
            if goal.get("deadline"):
                try:
                    deadline_value = datetime.date.fromisoformat(goal["deadline"])
                except ValueError:
                    deadline_value = None
            new_deadline = st.date_input("截止日期", value=deadline_value)
        with col_right:
            level_options = ["1  低", "2  较低", "3  中等", "4  重要", "5  非常重要"]
            current_level = max(0, min(4, int(goal.get("level") or 3) - 1))
            selected_level = st.radio("重要程度", level_options, index=current_level)
            new_level = level_options.index(selected_level) + 1

        new_tags_text = st.text_input(
            "标签（逗号分隔，可选）",
            value=", ".join(goal.get("tags", [])),
            placeholder="例如：英语学习, 六级, 实习准备",
        )

        save_col, cancel_col = st.columns(2)
        with save_col:
            saved = st.form_submit_button("保存", use_container_width=True)
        with cancel_col:
            cancelled = st.form_submit_button("取消", use_container_width=True)

    if saved and new_name.strip():
        new_tags = [item.strip() for item in new_tags_text.split(",") if item.strip()]
        for index, current_goal in enumerate(goals):
            if _goal_key(current_goal) == goal_id:
                goals[index] = {
                    **current_goal,
                    "goal": new_name.strip(),
                    "description": new_desc.strip(),
                    "deadline": str(new_deadline) if new_deadline else "",
                    "level": new_level,
                    "tags": new_tags,
                }
                break
        save_goals(goals)
        sync_goal_history(goal_id=goal_id, old_name=old_name, new_name=new_name.strip())
        st.session_state.editing_goal_id = None
        st.rerun()

    if cancelled:
        st.session_state.editing_goal_id = None
        st.rerun()


def render_goal_card(goal: dict, idx: int, section: str, cnt_map: dict, last_map: dict, goals: list):
    goal_id = _goal_key(goal)
    if st.session_state.get("editing_goal_id") == goal_id:
        _render_edit_form(goal, goals)
        return

    name = goal["goal"]
    description = goal.get("description", "")
    deadline = goal.get("deadline", "")
    tags = goal.get("tags", [])
    count = cnt_map.get(goal_id, 0)
    last_date = last_map.get(goal_id) or "从未"
    status = "断线" if count == 0 and bool(goals) else ("稳定" if count >= 3 else "推进中")
    badge_class = "b-alert" if status == "断线" else ("b-stable" if status == "稳定" else "b-mid")
    border_color = "#F59E0B" if status == "断线" else "#E5E7EB"
    heat = "".join(
        f'<span class="heat-cell" style="background:{"#4B6FD4" if index < count else "#E5E7EB"}"></span>'
        for index in range(7)
    )
    tag_html = _tag_badges(tags)
    description_html = (
        f'<div style="font-size:12px;color:#6B7280;margin-top:3px">{description}</div>'
        if description
        else ""
    )

    card_col, edit_col, del_col = st.columns([8, 1, 1])
    with card_col:
        st.markdown(
            f"""
<div class="goal-card card" style="border-color:{border_color};padding:16px 20px;margin-bottom:0">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div style="font-size:15px;font-weight:600;color:#1A1D23">{name}</div>
    <span class="badge {badge_class}">{status}</span>
  </div>
  {description_html}
  <div style="font-size:12px;color:#9CA3AF;margin-top:4px">
    {'截止 ' + deadline if deadline else '无截止日期'} · 最近推进：{last_date}
  </div>
  {('<div style="margin-top:6px">' + tag_html + '</div>') if tag_html else ""}
  <div style="margin-top:8px;font-size:11px;color:#9CA3AF">近 7 天 {heat}</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with edit_col:
        if st.button("编辑", key=f"edit_{section}_{idx}", help=f"编辑：{name}"):
            st.session_state.editing_goal_id = goal_id
            st.rerun()
    with del_col:
        if st.button("删除", key=f"del_{section}_{idx}", help=f"删除：{name}"):
            save_goals([item for item in goals if _goal_key(item) != goal_id])
            st.rerun()


def render_disc_card(goal: dict, idx: int, last_map: dict, goals: list):
    goal_id = _goal_key(goal)
    if st.session_state.get("editing_goal_id") == goal_id:
        _render_edit_form(goal, goals)
        return

    name = goal["goal"]
    last_date = last_map.get(goal_id) or "从未"
    card_col, edit_col, del_col = st.columns([8, 1, 1])
    with card_col:
        st.markdown(
            f"""
<div class="card card-yellow" style="padding:12px 18px;margin-bottom:0">
  <div style="font-size:14px;font-weight:600;color:#1A1D23">{name}</div>
  <div style="font-size:12px;color:#9CA3AF;margin-top:3px">最近推进：{last_date} · 近 7 天未完成相关任务</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with edit_col:
        if st.button("编辑", key=f"edit_disc_{idx}", help=f"编辑：{name}"):
            st.session_state.editing_goal_id = goal_id
            st.rerun()
    with del_col:
        if st.button("删除", key=f"del_disc_{idx}", help=f"删除：{name}"):
            save_goals([item for item in goals if _goal_key(item) != goal_id])
            st.rerun()
