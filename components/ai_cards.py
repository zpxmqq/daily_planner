from html import escape

import streamlit as st

from services.tracking_service import STATUS_COLOR, STATUS_LABEL

# Sentinel shown when the LLM returned valid JSON with an empty list for a
# given field. This is deliberately different from "暂无明显问题" (which reads
# as an affirmative "all good") — we want users to be able to tell apart
# "AI evaluated and said nothing to flag" from "AI did not answer this slot".
_EMPTY_SLOT_HTML = '<span style="color:#9CA3AF">AI 本轮未给出这一项</span>'


def _render_degraded_banner(data: dict) -> None:
    """Show a yellow warning strip when the LLM output is degraded.

    The normalizer sets ``degraded=True`` for: parse failures, API error
    envelopes, and all-empty-fields responses. Without this banner the UI
    silently renders blank sections and users can't distinguish "AI said
    everything is fine" from "AI didn't actually run".
    """
    if not data.get("degraded"):
        return
    reason = data.get("degraded_reason") or "AI 输出异常"
    excerpt = data.get("raw_excerpt") or ""
    message = f"⚠ AI 输出未通过校验：{reason}"
    if excerpt:
        message += f"\n\n原始片段：{excerpt}"
    st.warning(message)


def prog_bar(pct: int, color: str = "#4B6FD4") -> str:
    return f'<div class="prog-bg"><div class="prog-fill" style="width:{pct}%;background:{color}"></div></div>'


def render_ai_plan_card(data: dict):
    if data.get("error"):
        st.error(data["error"])
        return

    _render_degraded_banner(data)

    issues_html = "".join(f"<div>• {item}</div>" for item in data.get("issues", [])) or _EMPTY_SLOT_HTML
    focus_html = "".join(f'<div class="ai-highlight">• {item}</div>' for item in data.get("focus_tasks", []))
    adjustments_html = "".join(
        f"<div>• {item}</div>" for item in data.get("adjustments", [])
    ) or _EMPTY_SLOT_HTML

    st.markdown(
        f"""
<div class="card card-blue">
  <div class="sec-label">AI 计划评价</div>
  <div class="ai-block">
    <div class="ai-block-label">总体判断</div>
    <div class="ai-block-text">{data.get("overall", "—")}</div>
  </div>
  {"" if not data.get("covers_focus") else f'''<div class="ai-block">
    <div class="ai-block-label">阶段重点覆盖</div>
    <div class="ai-block-text">{data.get("covers_focus", "")}</div>
  </div>'''}
  {"" if not data.get("time_assessment") else f'''<div class="ai-block">
    <div class="ai-block-label">时间负荷判断</div>
    <div class="ai-block-text">{data.get("time_assessment", "")}</div>
  </div>'''}
  <div class="ai-block">
    <div class="ai-block-label">需要注意</div>
    <div class="ai-block-text">{issues_html}</div>
  </div>
  {"" if not focus_html else f'''<div class="ai-block">
    <div class="ai-block-label">今日重点任务</div>
    {focus_html}
  </div>'''}
  <div class="ai-block">
    <div class="ai-block-label">建议调整</div>
    <div class="ai-block-text">{adjustments_html}</div>
  </div>
  {"" if not data.get("top_priority") else f'''<div class="ai-block">
    <div class="ai-block-label">今天最重要的一件事</div>
    <div class="ai-highlight" style="font-size:13px;font-weight:600">• {data.get("top_priority", "")}</div>
  </div>'''}
</div>
""",
        unsafe_allow_html=True,
    )


def render_ai_review_card(data: dict):
    if data.get("error"):
        st.error(data["error"])
        return

    _render_degraded_banner(data)

    st.markdown(
        f"""
<div class="card card-green">
  <div class="sec-label">AI 复盘</div>
  <div class="ai-block">
    <div class="ai-block-label">完成度评价</div>
    <div class="ai-block-text">{data.get("score", "—")}</div>
  </div>
  {"" if not data.get("real_progress") else f'''<div class="ai-block">
    <div class="ai-block-label">今天真正推进了什么</div>
    <div class="ai-block-text">{data.get("real_progress", "")}</div>
  </div>'''}
  {"" if not data.get("weak_lines") else f'''<div class="ai-block">
    <div class="ai-block-label">今天推进较弱的线</div>
    <div class="ai-block-text" style="color:#F59E0B">{data.get("weak_lines", "")}</div>
  </div>'''}
  {"" if not data.get("focus_insight") else f'''<div class="ai-block" style="background:#EEF2FF;border-left:3px solid #6366F1;padding:10px 12px;border-radius:6px">
    <div class="ai-block-label">💡 专注度洞察</div>
    <div class="ai-block-text" style="color:#3730A3">{data.get("focus_insight", "")}</div>
  </div>'''}
  <div class="ai-block">
    <div class="ai-block-label">明天最重要的一步</div>
    <div class="ai-highlight" style="font-size:13px;font-weight:600">• {data.get("tomorrow", "—")}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _truncate_with_tooltip(text: str, limit: int = 120) -> str:
    """Render long text with a soft cap + native ``title`` tooltip for overflow.

    Old behavior truncated at 57 chars + "..." which eats action-detail
    phrases like "晚 21:00 之前完成实验表". We now surface up to 120 chars
    inline and keep the full text available on hover.
    """
    safe_full = escape(text or "")
    if len(text or "") <= limit:
        return safe_full
    shown = escape(text[: limit - 1]) + "…"
    return f'<span title="{safe_full}">{shown}</span>'


_CONFIDENCE_BADGE = {
    "low": ("低置信度 · 建议人工确认", "#9CA3AF"),
    "medium": ("中等置信度", "#6B7280"),
    "high": ("高置信度", "#10B981"),
}


def _confidence_badge_html(tracking: dict) -> str:
    if not tracking.get("auto_judged", True):
        return '<span class="badge" style="background:#6366F1;color:#fff;font-size:10px;margin-left:6px">用户已修正</span>'
    confidence = tracking.get("confidence")
    if not confidence or confidence not in _CONFIDENCE_BADGE:
        return ""
    text, color = _CONFIDENCE_BADGE[confidence]
    return (
        f'<span class="badge" style="background:{color};color:#fff;font-size:10px;margin-left:6px">'
        f"{text}</span>"
    )


def render_suggestion_tracking_card(tracking: dict, date: str = ""):
    status = tracking.get("status", "not_obvious")
    label = STATUS_LABEL.get(status, status)
    color = STATUS_COLOR.get(status, "#9CA3AF")
    reason = tracking.get("reason", "")
    raw_suggestion = tracking.get("source_tomorrow") or tracking.get("source_top_priority") or "—"
    suggestion_display = _truncate_with_tooltip(raw_suggestion, limit=120)
    confidence_html = _confidence_badge_html(tracking)

    st.markdown(
        f"""
<div class="card" style="border-left:4px solid {color};padding:16px 20px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <div style="font-size:12px;font-weight:700;color:#6B7280;text-transform:uppercase;letter-spacing:.06em">建议追踪情况</div>
    <div>
      <span class="badge" style="background:{color};color:#fff;font-size:11px">{label}</span>
      {confidence_html}
    </div>
  </div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:6px">昨日建议（{escape(tracking.get("source_date", ""))}）：{suggestion_display}</div>
  <div style="font-size:13px;color:#374151">{escape(reason)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("修正判断（可选）", expanded=False):
        st.caption("系统默认自动判断，只有在明显误判时才需要手动修正。")
        options = ["done", "partial", "not_obvious"]
        labels = [STATUS_LABEL[item] for item in options]
        current_index = options.index(status) if status in options else 2
        selected = st.selectbox(
            "修正结果",
            labels,
            index=current_index,
            key="tracking_correction_sel",
            label_visibility="collapsed",
        )
        if st.button("保存修正", key="tracking_correction_save"):
            new_status = options[labels.index(selected)]
            new_tracking = {
                **tracking,
                "status": new_status,
                "reason": tracking.get("reason", "") + f"（用户手动修正为：{STATUS_LABEL[new_status]}）",
                "auto_judged": False,
            }
            from config.settings import TODAY
            from data.repository import upsert_record

            target_date = date or TODAY
            upsert_record(date=target_date, suggestion_tracking=new_tracking)
            st.session_state.tracking_result = new_tracking
            st.success("已保存修正。")
            st.rerun()


def render_tracking_summary_card(tracking: dict):
    if not tracking or not tracking.get("status"):
        st.markdown(
            """
<div class="card" style="padding:16px 18px;color:#9CA3AF">
  还没有可展示的建议追踪结果。
</div>
""",
            unsafe_allow_html=True,
        )
        return

    status = tracking.get("status", "not_obvious")
    label = STATUS_LABEL.get(status, status)
    color = STATUS_COLOR.get(status, "#9CA3AF")
    raw_suggestion = tracking.get("source_tomorrow") or tracking.get("source_top_priority") or "—"
    suggestion = _truncate_with_tooltip(raw_suggestion, limit=120)
    confidence_html = _confidence_badge_html(tracking)

    st.markdown(
        f"""
<div class="card" style="border-left:4px solid {color};padding:16px 18px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <div style="font-size:12px;font-weight:700;color:#6B7280;text-transform:uppercase;letter-spacing:.06em">昨日建议追踪</div>
    <div>
      <span class="badge" style="background:{color};color:#fff;font-size:11px">{label}</span>
      {confidence_html}
    </div>
  </div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:6px">来源：{escape(tracking.get("source_date", ""))} · {suggestion}</div>
  <div style="font-size:13px;color:#374151">{escape(tracking.get("reason", ""))}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_rag_debug_card(debug: dict, title: str = "RAG 检索调试"):
    if not debug:
        return

    embedding = debug.get("embedding", {}) or {}
    backend = embedding.get("backend", "disabled")
    model = embedding.get("model", "") or "未启用"
    query_text = debug.get("query_text", "").strip()
    goal_ids = debug.get("goal_ids", []) or []
    tags = debug.get("tags", []) or []
    hits = debug.get("hits", []) or []

    badge_color = "#10B981" if backend == "api" else "#4B6FD4" if backend == "local" else "#9CA3AF"
    badge_label = "API" if backend == "api" else "本地 fallback" if backend == "local" else "未启用"

    with st.expander(title, expanded=False):
        st.markdown(
            f"""
<div class="card" style="padding:14px 16px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <div style="font-size:12px;font-weight:700;color:#6B7280;text-transform:uppercase;letter-spacing:.06em">Embedding 后端</div>
    <span class="badge" style="background:{badge_color};color:#fff;font-size:11px">{badge_label}</span>
  </div>
  <div style="font-size:12px;color:#374151">模型：{model}</div>
  <div style="font-size:12px;color:#6B7280;margin-top:4px">{embedding.get("note", "")}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        if query_text:
            st.caption("检索查询")
            st.code(query_text, language="text")

        if goal_ids or tags:
            meta_bits = []
            if goal_ids:
                meta_bits.append("goal_id: " + ", ".join(goal_ids))
            if tags:
                meta_bits.append("tags: " + ", ".join(tags))
            st.caption("检索元数据：" + " | ".join(meta_bits))

        if not hits:
            st.info("这次没有命中相关历史。若当前使用本地 fallback，也可以正常演示检索链路。")
            return

        for hit in hits:
            label = "晨间计划" if hit.get("chunk_type") == "plan_chunk" else "晚间复盘"
            summary = hit.get("summary_text", "").strip() or "无摘要"
            st.markdown(
                f"""
<div class="card" style="padding:14px 16px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
    <div style="font-size:13px;font-weight:600;color:#1A1D23">{hit.get("record_date", "")} | {label}</div>
    <span class="badge b-mid" style="font-size:10px">score {hit.get("score", 0):.3f}</span>
  </div>
  <div style="font-size:12px;color:#374151;margin-top:6px">{summary}</div>
  <div style="font-size:11px;color:#9CA3AF;margin-top:8px">
    semantic={hit.get("semantic_score", 0):.3f} |
    recency={hit.get("recency_boost", 0):.3f} |
    overlap={hit.get("metadata_boost", 0):.3f}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
