import streamlit as st

from pages.goals import render_goals_editor
from pages.profile import render_profile_editor


def page_personal():
    st.markdown('<div class="page-title">个人信息</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">这里收纳长期背景和长期目标。首页不再占用显眼位置，需要时再进来调整。</div>',
        unsafe_allow_html=True,
    )

    back_col, _ = st.columns([1, 6])
    with back_col:
        if st.button("返回首页", key="personal_back_to_dashboard"):
            st.session_state.page = "dashboard"
            st.rerun()

    tab_profile, tab_goals = st.tabs(["背景档案", "长期目标"])

    with tab_profile:
        render_profile_editor(show_header=False)

    with tab_goals:
        render_goals_editor(show_header=False)
