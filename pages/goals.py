import streamlit as st

from config.settings import TODAY
from data.repository import load_goals, load_history, save_goals
from services.goal_service import compute_goal_stats
from components.goal_card import render_disc_card, render_goal_card


def render_goals_editor(show_header: bool = True):
    if show_header:
        st.markdown('<div class="page-title">目标管理</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="page-sub">维护长期目标，看看哪些线在稳定推进，哪些线开始掉队。</div>',
            unsafe_allow_html=True,
        )

    goals = load_goals()
    history = load_history()
    cnt_map, last_map, disc_goals, top_goals, other_goals = compute_goal_stats(goals, history)

    col_main, col_add = st.columns([3, 2], gap="medium")

    with col_main:
        if top_goals:
            st.markdown('<div class="sec-label">重要目标</div>', unsafe_allow_html=True)
            for idx, goal in enumerate(top_goals):
                render_goal_card(goal, idx, section="top", cnt_map=cnt_map, last_map=last_map, goals=goals)

        if disc_goals:
            st.markdown('<div class="sec-label" style="color:#F59E0B">最近掉队的目标</div>', unsafe_allow_html=True)
            for idx, goal in enumerate(disc_goals):
                render_disc_card(goal, idx, last_map=last_map, goals=goals)

        remaining = [goal for goal in other_goals if goal not in disc_goals]
        if remaining:
            st.markdown('<div class="sec-label">其他目标</div>', unsafe_allow_html=True)
            for idx, goal in enumerate(remaining):
                render_goal_card(goal, idx, section="other", cnt_map=cnt_map, last_map=last_map, goals=goals)

        if not goals:
            st.markdown(
                '<div class="card" style="color:#9CA3AF;text-align:center;padding:36px">还没有目标，从右侧添加第一个长期目标吧。</div>',
                unsafe_allow_html=True,
            )

    with col_add:
        st.markdown('<div class="sec-label">添加新目标</div>', unsafe_allow_html=True)
        with st.container():
            new_name = st.text_input("目标名称", placeholder="例如：通过英语六级", key="new_goal_name")
            new_desc = st.text_input("描述（可选）", placeholder="一句话说明这个目标", key="new_goal_desc")
            new_deadline = st.date_input("截止日期（可选）", value=None, key="new_goal_deadline")
            level_options = ["1  低", "2  较低", "3  中等", "4  重要", "5  非常重要"]
            level_selected = st.radio("重要程度", level_options, index=2, key="new_goal_level")
            selected_level = level_options.index(level_selected) + 1
            tags_text = st.text_input(
                "标签（逗号分隔，可选）",
                placeholder="例如：英语学习, 六级, 实习准备",
                key="new_goal_tags",
            )

            if st.button("添加目标", use_container_width=True, key="add_goal"):
                if not new_name.strip():
                    st.warning("请输入目标名称。")
                else:
                    tags = [item.strip() for item in tags_text.split(",") if item.strip()]
                    goals.append(
                        {
                            "goal": new_name.strip(),
                            "description": new_desc.strip(),
                            "level": selected_level,
                            "deadline": str(new_deadline) if new_deadline else "",
                            "created": TODAY,
                            "tags": tags,
                        }
                    )
                    save_goals(goals)
                    st.success("目标已添加。")
                    st.rerun()


def page_goals():
    render_goals_editor(show_header=True)
