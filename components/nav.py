import streamlit as st

NAV_ITEMS = [
    ("dashboard", "首页"),
    ("plan", "今日计划"),
    ("review", "晚间复盘"),
    ("history", "历史"),
    ("time_analysis", "时间分析"),
]


def render_nav():
    cols = st.columns(len(NAV_ITEMS))
    for index, (key, label) in enumerate(NAV_ITEMS):
        with cols[index]:
            active = st.session_state.page == key
            display = f"**{label}**" if active else label
            if st.button(display, key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key
                st.rerun()
