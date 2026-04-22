import streamlit as st

st.set_page_config(
    page_title="每日规划助手",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from components.css import inject_css
from components.nav import render_nav
from pages.dashboard import page_dashboard
from pages.goals import page_goals
from pages.history import page_history
from pages.personal import page_personal
from pages.plan import page_plan
from pages.profile import page_profile
from pages.review import page_review
from pages.time_analysis import page_time_analysis


if "page" not in st.session_state:
    st.session_state.page = "dashboard"
if "draft_tasks" not in st.session_state:
    st.session_state.draft_tasks = []
if "draft_tasks_date" not in st.session_state:
    st.session_state.draft_tasks_date = None
if "plan_ai_result" not in st.session_state:
    st.session_state.plan_ai_result = None
if "review_ai_result" not in st.session_state:
    st.session_state.review_ai_result = None
if "editing_goal_id" not in st.session_state:
    st.session_state.editing_goal_id = None
if "tracking_result" not in st.session_state:
    st.session_state.tracking_result = None
if "plan_rag_debug" not in st.session_state:
    st.session_state.plan_rag_debug = None
if "review_rag_debug" not in st.session_state:
    st.session_state.review_rag_debug = None

inject_css()
render_nav()

{
    "dashboard": page_dashboard,
    "personal": page_personal,
    "goals": page_goals,
    "profile": page_profile,
    "plan": page_plan,
    "review": page_review,
    "history": page_history,
    "time_analysis": page_time_analysis,
}.get(st.session_state.page, page_dashboard)()
