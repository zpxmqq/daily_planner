"""Time analysis page · tag-level pie chart + planned-vs-actual scatter.

Reads from ``history_tasks.actual_minutes`` — so both timer-captured and
manually filled time entries surface here.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import streamlit as st

try:
    import plotly.express as px
except ImportError:  # pragma: no cover - optional dep
    px = None

from data.repository import load_history


RANGE_OPTIONS = {
    "今天": 0,
    "7 天": 7,
    "30 天": 30,
}


def _date_window(choice: str) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    span = RANGE_OPTIONS.get(choice, 7)
    if span == 0:
        return today, today
    return today - dt.timedelta(days=span - 1), today


def _collect_tasks(history: list[dict], start: dt.date, end: dt.date) -> list[dict]:
    window = []
    for record in history or []:
        try:
            record_date = dt.date.fromisoformat(record.get("date", ""))
        except ValueError:
            continue
        if not (start <= record_date <= end):
            continue
        for task in record.get("tasks", []) or []:
            if int(task.get("actual_minutes", 0) or 0) <= 0:
                continue
            window.append(
                {
                    "date": record.get("date", ""),
                    "text": task.get("text", ""),
                    "tag": str(task.get("tag") or "未分类").strip() or "未分类",
                    "duration": int(task.get("duration", 0) or 0),
                    "actual_minutes": int(task.get("actual_minutes", 0) or 0),
                    "unplanned": bool(task.get("unplanned")),
                }
            )
    return window


def _aggregate_by_tag(tasks: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for task in tasks:
        totals[task["tag"]] += task["actual_minutes"]
    return dict(totals)


def _render_empty():
    st.markdown(
        """
<div class="card" style="text-align:center;padding:48px 20px;color:#9CA3AF">
  <div style="font-size:14px;font-weight:500">还没有实际用时数据</div>
  <div style="font-size:12px;margin-top:6px">在"今日计划"用 ▶️ 按钮记录一次专注，或在"晚间复盘"手填实际用时，就能在这里看到分布。</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _format_minutes(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes < 60:
        return f"{minutes}min"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours}h"
    return f"{hours}h{rest}min"


def _accuracy_insight(tasks: list[dict]) -> list[str]:
    """Return textual insights about estimation accuracy."""
    if not tasks:
        return []
    with_plan = [t for t in tasks if t["duration"] > 0]
    if not with_plan:
        return []

    within_band = sum(1 for t in with_plan if abs(t["actual_minutes"] - t["duration"]) / t["duration"] <= 0.20)
    accuracy = within_band / len(with_plan)

    per_tag_pct: dict[str, list[float]] = defaultdict(list)
    for task in with_plan:
        pct = (task["actual_minutes"] - task["duration"]) / task["duration"]
        per_tag_pct[task["tag"]].append(pct)

    worst_tag = ""
    worst_pct = 0.0
    for tag, pcts in per_tag_pct.items():
        if len(pcts) < 2:
            continue
        avg = sum(pcts) / len(pcts)
        if abs(avg) > abs(worst_pct):
            worst_pct = avg
            worst_tag = tag

    lines = [f"预估准确率：{accuracy * 100:.0f}% 的任务实际用时在预计的 ±20% 内（共 {len(with_plan)} 条）"]
    if worst_tag:
        direction = "超出" if worst_pct > 0 else "低于"
        lines.append(f"最不准的类别是 '{worst_tag}'（平均{direction}预计 {abs(worst_pct) * 100:.0f}%）")
    return lines


def page_time_analysis():
    st.markdown('<div class="page-title">时间分析</div>', unsafe_allow_html=True)
    st.caption("基于任务的实际用时（计时器 + 手填）聚合。")

    choice = st.radio(
        "日期范围",
        list(RANGE_OPTIONS.keys()),
        index=1,
        horizontal=True,
        key="time_analysis_range",
    )
    start, end = _date_window(choice)
    st.caption(f"统计范围：{start.isoformat()} ～ {end.isoformat()}")

    history = load_history()
    tasks = _collect_tasks(history, start, end)

    if not tasks:
        _render_empty()
        return

    total_minutes = sum(task["actual_minutes"] for task in tasks)
    tag_totals = _aggregate_by_tag(tasks)

    st.markdown('<div class="sec-label">各标签实际用时占比</div>', unsafe_allow_html=True)
    if px is None:
        st.warning("未安装 plotly，展示为文字表。可执行 `pip install plotly>=5.0` 启用图表。")
        for tag, minutes in sorted(tag_totals.items(), key=lambda item: -item[1]):
            pct = minutes / total_minutes * 100 if total_minutes else 0
            st.markdown(f"- **{tag}** · {_format_minutes(minutes)} · {pct:.1f}%")
    else:
        pie = px.pie(
            names=list(tag_totals.keys()),
            values=list(tag_totals.values()),
            hole=0.45,
        )
        pie.update_traces(
            hovertemplate="<b>%{label}</b><br>%{value} 分钟<br>%{percent}<extra></extra>",
            textinfo="label+percent",
        )
        pie.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10), showlegend=True)
        st.plotly_chart(pie, use_container_width=True)

    st.markdown('<div class="sec-label" style="margin-top:8px">预计 vs 实际</div>', unsafe_allow_html=True)
    scatter_tasks = [t for t in tasks if t["duration"] > 0]
    if not scatter_tasks:
        st.caption("这段时间没有「预计-实际」两项都齐全的任务。")
    elif px is None:
        for task in scatter_tasks:
            st.markdown(
                f"- {task['text']}｜预计 {_format_minutes(task['duration'])} / 实际 {_format_minutes(task['actual_minutes'])}"
            )
    else:
        max_minutes = max(
            max(t["duration"] for t in scatter_tasks),
            max(t["actual_minutes"] for t in scatter_tasks),
        )
        scatter = px.scatter(
            scatter_tasks,
            x="duration",
            y="actual_minutes",
            color="tag",
            hover_data={"text": True, "date": True, "unplanned": True},
            labels={"duration": "预计（分钟）", "actual_minutes": "实际（分钟）"},
        )
        # y = x 对角线
        scatter.add_shape(
            type="line",
            x0=0,
            y0=0,
            x1=max_minutes,
            y1=max_minutes,
            line=dict(color="#9CA3AF", dash="dash"),
        )
        scatter.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(scatter, use_container_width=True)

    st.markdown('<div class="sec-label" style="margin-top:8px">文字洞察</div>', unsafe_allow_html=True)
    biggest_tag, biggest_minutes = max(tag_totals.items(), key=lambda item: item[1])
    pct_of_total = biggest_minutes / total_minutes * 100 if total_minutes else 0
    lines = [
        f"过去 {choice}你在 **{biggest_tag}** 投入 {_format_minutes(biggest_minutes)}（占比 {pct_of_total:.0f}%），"
        f"实际记录总时长 {_format_minutes(total_minutes)}。"
    ]
    lines.extend(_accuracy_insight(tasks))
    unplanned_minutes = sum(task["actual_minutes"] for task in tasks if task["unplanned"])
    if unplanned_minutes:
        lines.append(f"其中有 {_format_minutes(unplanned_minutes)} 花在标记为「突发」的任务上。")
    st.markdown("\n".join(f"- {line}" for line in lines))
