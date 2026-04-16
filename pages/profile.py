import streamlit as st

from config.settings import TODAY
from data.repository import load_profile, save_profile
from services.llm_service import extract_profile_from_long_text


PROFILE_FIELDS = ("main_goal", "current_focus", "priorities", "constraints", "not_urgent")
FEEDBACK_STYLE_OPTIONS = {
    "gentle": "温和型：更鼓励、更稳，适合压力大时",
    "rational": "理性型：默认推荐，分析更克制清晰",
    "strict": "严格型：更直接，更强调缺口和优先级",
}


def _state_key(field: str) -> str:
    return f"profile_{field}"


def _bootstrap_profile_state(profile: dict):
    for field in (*PROFILE_FIELDS, "career_plan_text"):
        key = _state_key(field)
        if key not in st.session_state:
            st.session_state[key] = profile.get(field, "")
    if _state_key("feedback_style") not in st.session_state:
        st.session_state[_state_key("feedback_style")] = profile.get("feedback_style", "rational")


def render_profile_editor(show_header: bool = True):
    profile = load_profile()
    _bootstrap_profile_state(profile)

    if show_header:
        st.markdown('<div class="page-title">长期背景档案</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="page-sub">让 AI 先理解你的长期方向，再给出更贴合现实节奏的计划和复盘建议。</div>',
            unsafe_allow_html=True,
        )

    if profile.get("updated"):
        st.caption(f"上次更新：{profile['updated']}")

    st.markdown('<div class="sec-label">职业规划长文本输入</div>', unsafe_allow_html=True)
    st.text_area(
        "职业规划长文本",
        key=_state_key("career_plan_text"),
        placeholder="可以直接粘贴一整段职业规划、阶段安排或学习重点，AI 会帮你抽取成结构化长期背景。",
        height=140,
        label_visibility="collapsed",
    )
    if st.button("AI 提取长期背景", use_container_width=True, key="extract_profile_from_text"):
        long_text = st.session_state[_state_key("career_plan_text")].strip()
        if not long_text:
            st.warning("先输入一段职业规划或阶段安排，再让 AI 提取。")
        else:
            with st.spinner("AI 正在提取长期背景..."):
                extracted = extract_profile_from_long_text(long_text)
            st.session_state.profile_extracted_result = extracted
            if extracted.get("error"):
                st.warning(extracted["error"])
            else:
                for field in PROFILE_FIELDS:
                    if extracted.get(field):
                        st.session_state[_state_key(field)] = extracted[field]
                st.success("已提取结构化背景，你可以继续微调后再保存。")

    extracted = st.session_state.get("profile_extracted_result")
    if extracted and not extracted.get("error"):
        preview_rows = "".join(
            f'<div style="margin-bottom:8px"><div style="font-size:11px;color:#9CA3AF">{label}</div>'
            f'<div style="font-size:13px;color:#374151">{value or "—"}</div></div>'
            for label, value in (
                ("当前总目标", extracted.get("main_goal", "")),
                ("当前阶段重点", extracted.get("current_focus", "")),
                ("近期优先事项", extracted.get("priorities", "")),
                ("当前约束条件", extracted.get("constraints", "")),
                ("当前不需要猛冲的事项", extracted.get("not_urgent", "")),
            )
        )
        st.markdown(f'<div class="card" style="padding:16px 18px">{preview_rows}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec-label" style="margin-top:14px">结构化长期背景</div>', unsafe_allow_html=True)
    st.text_input(
        "当前总目标",
        key=_state_key("main_goal"),
        placeholder="例如：为暑期实习和毕业准备打基础",
    )
    st.text_area(
        "当前阶段重点",
        key=_state_key("current_focus"),
        placeholder="例如：英语六级、课程任务、项目优化",
        height=72,
    )
    st.text_area(
        "近期优先事项",
        key=_state_key("priorities"),
        placeholder="例如：论文和六级优先于新方向探索",
        height=72,
    )
    st.text_input(
        "当前约束条件",
        key=_state_key("constraints"),
        placeholder="例如：上课、期末、每天健身、周会",
    )
    st.text_input(
        "当前不需要猛冲的事项（可选）",
        key=_state_key("not_urgent"),
        placeholder="例如：副业、额外框架学习暂时放缓",
    )
    st.selectbox(
        "AI 反馈风格",
        list(FEEDBACK_STYLE_OPTIONS.keys()),
        format_func=lambda key: FEEDBACK_STYLE_OPTIONS[key],
        key=_state_key("feedback_style"),
    )

    if st.button("保存档案", use_container_width=True, key="save_profile_btn"):
        save_profile(
            {
                "main_goal": st.session_state[_state_key("main_goal")].strip(),
                "current_focus": st.session_state[_state_key("current_focus")].strip(),
                "priorities": st.session_state[_state_key("priorities")].strip(),
                "constraints": st.session_state[_state_key("constraints")].strip(),
                "not_urgent": st.session_state[_state_key("not_urgent")].strip(),
                "feedback_style": st.session_state[_state_key("feedback_style")],
                "career_plan_text": st.session_state[_state_key("career_plan_text")].strip(),
                "updated": TODAY,
            }
        )
        st.success("档案已保存，后续晨间评价和晚间复盘都会自动读取这些背景信息。")
        st.rerun()

    current_values = [st.session_state[_state_key(field)] for field in PROFILE_FIELDS]
    if any(current_values):
        rows = "".join(
            f'<div style="margin-bottom:10px"><div style="font-size:11px;color:#9CA3AF;font-weight:600">{label}</div>'
            f'<div style="font-size:13px;color:#374151;margin-top:2px">{value or "—"}</div></div>'
            for label, value in (
                ("当前总目标", st.session_state[_state_key("main_goal")]),
                ("当前阶段重点", st.session_state[_state_key("current_focus")]),
                ("近期优先事项", st.session_state[_state_key("priorities")]),
                ("当前约束条件", st.session_state[_state_key("constraints")]),
                ("当前不需要猛冲的事项", st.session_state[_state_key("not_urgent")]),
                ("AI 反馈风格", FEEDBACK_STYLE_OPTIONS[st.session_state[_state_key("feedback_style")]]),
            )
        )
        st.markdown(f'<div class="card" style="padding:20px;margin-top:14px">{rows}</div>', unsafe_allow_html=True)


def page_profile():
    render_profile_editor(show_header=True)
