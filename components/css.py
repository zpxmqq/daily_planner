import streamlit as st


def inject_css():
    st.markdown("""
<style>
/* ── 基础 ── */
.stApp { background: #F4F5F7; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.2rem !important; max-width: 980px; }

/* ── 按钮 ── */
.stButton > button {
    border-radius: 8px; font-weight: 500; font-size: 14px;
    border: 1px solid #E5E7EB; background: white; color: #374151;
    transition: all .15s ease;
}
.stButton > button:hover {
    border-color: #4B6FD4; color: #4B6FD4; background: #EEF2FF;
}

/* ── 输入框 ── */
.stTextArea textarea, .stTextInput input {
    border-radius: 8px !important; font-size: 14px !important;
    background: white !important;
}

/* ── 选择框 ── */
.stSelectbox > div { border-radius: 8px !important; }

/* ── Tab ── */
.stTabs [data-baseweb="tab-list"] { gap: 6px; background: transparent; border-bottom: 1px solid #E5E7EB; }
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0; padding: 8px 20px;
    font-weight: 500; font-size: 14px; color: #6B7280;
    background: transparent; border: none !important;
}
.stTabs [aria-selected="true"] {
    color: #4B6FD4 !important; background: transparent !important;
    border-bottom: 2px solid #4B6FD4 !important;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 20px; }

/* ── 分隔线 ── */
hr { border: none; border-top: 1px solid #E5E7EB; margin: 12px 0; }

/* ── 卡片 ── */
.card {
    background: white; border-radius: 12px; padding: 20px 24px;
    margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    border: 1px solid #F0F1F3;
}
.card-blue   { border-left: 3px solid #4B6FD4; }
.card-green  { border-left: 3px solid #10B981; }
.card-yellow { border-left: 3px solid #F59E0B; }

/* ── 文字层级 ── */
.page-title { font-size: 22px; font-weight: 700; color: #1A1D23; margin-bottom: 4px; }
.page-sub   { font-size: 14px; color: #6B7280; margin-bottom: 20px; }
.sec-label  {
    font-size: 11px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: #9CA3AF; margin: 14px 0 8px;
}

/* ── AI 结果模块 ── */
.ai-block {
    background: #FAFBFF; border-radius: 10px; padding: 14px 18px;
    margin-bottom: 10px; border: 1px solid #E8ECFF;
}
.ai-block-label {
    font-size: 11px; font-weight: 700; color: #4B6FD4;
    text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px;
}
.ai-block-text { font-size: 14px; color: #374151; line-height: 1.65; }
.ai-highlight  {
    background: #EEF2FF; border-radius: 6px; padding: 10px 14px;
    font-size: 14px; font-weight: 500; color: #3730A3; margin-top: 6px;
}

/* ── Badge ── */
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600; margin-right: 4px;
}
.b-high   { background: #FEF3C7; color: #92400E; }
.b-mid    { background: #EEF2FF; color: #3730A3; }
.b-low    { background: #F3F4F6; color: #6B7280; }
.b-done   { background: #ECFDF5; color: #065F46; }
.b-alert  { background: #FEE2E2; color: #991B1B; }
.b-stable { background: #ECFDF5; color: #065F46; }

/* ── 进度条 ── */
.prog-bg   { background: #F3F4F6; border-radius: 4px; height: 5px; margin: 6px 0; }
.prog-fill { height: 5px; border-radius: 4px; }

/* ── 热力格 ── */
.heat-cell {
    width: 22px; height: 22px; border-radius: 4px;
    display: inline-block; margin: 2px;
}

/* ── 导航 ── */
.nav-wrap {
    display: flex; gap: 4px; padding-bottom: 16px;
    border-bottom: 1px solid #E5E7EB; margin-bottom: 20px;
}
</style>
""", unsafe_allow_html=True)
