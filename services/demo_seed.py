"""Demo seed data loader.

Cold-start problem: a new user opens the app and sees empty states on every
page — no goals, no history, no RAG hits, no tracking card. The "closed
loop" story only emerges after 2–3 days of real data, which makes demos
and fresh-install evaluations frustrating.

This module seeds 3 days of plausible data (today - 2, today - 1, today)
plus 3 long-term goals and a profile, so the full loop — plan review →
tracking → RAG → time analysis — is visible on first open.

Design choices:
- Content is generic (学习 / 健身 / 阅读 / 写作) so it doesn't impose the
  author's domain on the new user.
- Everything is routed through the repository's public upsert_record /
  save_goals / save_profile API; no direct SQL.
- The function returns a status dict so the caller can surface what was
  written.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from data.repository import load_goals, load_history, save_goals, save_profile, upsert_record

LOGGER = logging.getLogger(__name__)


def _goal(name: str, level: int, tags: list[str], description: str, deadline_days: int | None = None) -> dict:
    gid = uuid.uuid4().hex[:8]
    goal: dict = {
        "goal_id": gid,
        "goal": name,
        "level": level,
        "tags": tags,
        "description": description,
    }
    if deadline_days is not None:
        goal["deadline"] = str(dt.date.today() + dt.timedelta(days=deadline_days))
    return goal


def _task(text: str, duration: int, priority: str, goal_name: str, tag: str,
          done: bool, actual_minutes: int = 0, note: str = "", must: bool = False) -> dict:
    return {
        "text": text,
        "duration": duration,
        "priority": priority,
        "goal": goal_name,
        "tag": tag,
        "done": done,
        "actual_minutes": actual_minutes,
        "note": note,
        "must": must,
    }


def seed_demo_data(force: bool = False) -> dict:
    """Load 3 days of demo data.

    Returns ``{"status": "seeded|skipped|partial", "goals": n, "records": n}``.

    When ``force=False`` and there's already non-trivial data (>= 1 goal or
    >= 2 history records), we skip seeding to avoid clobbering real data.
    """
    existing_goals = load_goals() or []
    existing_history = load_history() or []
    if not force and (len(existing_goals) >= 1 or len(existing_history) >= 2):
        return {
            "status": "skipped",
            "reason": "existing data detected; pass force=True to overwrite",
            "goals": len(existing_goals),
            "records": len(existing_history),
        }

    today = dt.date.today()
    d2 = str(today - dt.timedelta(days=2))
    d1 = str(today - dt.timedelta(days=1))
    d0 = str(today)

    # --- Goals -----------------------------------------------------------
    goals = [
        _goal(
            "完成阶段学习目标",
            level=5,
            tags=["学习", "课程"],
            description="当前阶段最重要的长期线，优先保障。",
            deadline_days=30,
        ),
        _goal(
            "保持每周 3 次健身",
            level=3,
            tags=["健身"],
            description="维持身体状态，不要求猛冲。",
        ),
        _goal(
            "完成一本书的阅读",
            level=2,
            tags=["阅读"],
            description="碎片时间推进，优先级低于学习。",
            deadline_days=45,
        ),
    ]
    save_goals(goals)
    goal_study = goals[0]["goal"]
    goal_gym = goals[1]["goal"]
    goal_read = goals[2]["goal"]

    # --- Profile ---------------------------------------------------------
    save_profile(
        {
            "main_goal": "本阶段以学习目标为主线，稳定推进",
            "current_focus": "完成核心学习任务、保持基础运动量",
            "priorities": "学习 > 健身 > 阅读",
            "constraints": "工作日白天有 2-3 小时空档，晚上易疲劳",
            "not_urgent": "拓展类新方向本月不猛冲",
            "feedback_style": "rational",
            "career_plan_text": "（示例档案，可以在本页继续微调）",
            "updated": d0,
        }
    )

    # --- Day -2: executed well, with time tracking -----------------------
    tasks_d2 = [
        _task("完成学习章节 A（含练习题）", duration=90, priority="high",
              goal_name=goal_study, tag="学习", done=True, actual_minutes=110,
              note="写完了，题目比预期难，花的时间超了。", must=True),
        _task("晨跑 5 公里", duration=40, priority="medium",
              goal_name=goal_gym, tag="健身", done=True, actual_minutes=45,
              note="状态不错。"),
        _task("阅读 30 页", duration=30, priority="low",
              goal_name=goal_read, tag="阅读", done=False),
    ]
    upsert_record(
        date=d2,
        tasks=tasks_d2,
        result="学习线推进到位，但耗时明显超出预计。",
        status="顺利",
        top_priority="完成学习章节 A 的练习题并对难点做笔记。",
        tomorrow_suggestion="明天上午把学习章节 B 的核心概念写成一页 summary。",
        ai_plan_result={
            "overall": "计划方向正确，学习线被守住了。",
            "covers_focus": "覆盖了当前阶段重点。",
            "issues": ["阅读放在一天最末，容易被跳过。"],
            "focus_tasks": ["完成学习章节 A"],
            "adjustments": ["把阅读拆成 15 分钟 × 2，插到午休和晚间。"],
            "time_assessment": "适中偏紧。",
            "top_priority": "完成学习章节 A 的练习题并对难点做笔记。",
            "degraded": False,
        },
        ai_review_result={
            "score": "核心任务完成，次级任务掉队。",
            "real_progress": "学完学习章节 A 并写完练习题。",
            "weak_lines": "阅读线本日未推进，是次级目标的正常波动。",
            "tomorrow": "明天上午把学习章节 B 的核心概念写成一页 summary。",
            "focus_insight": "学习任务超估 22%，下次把基准从 90 分钟调到 110 分钟。",
            "degraded": False,
        },
    )

    # --- Day -1: partial execution ---------------------------------------
    tasks_d1 = [
        _task("学习章节 B 概念 summary", duration=90, priority="high",
              goal_name=goal_study, tag="学习", done=True, actual_minutes=75,
              note="写完了，比预期快。", must=True),
        _task("健身房力量训练", duration=60, priority="medium",
              goal_name=goal_gym, tag="健身", done=False, note="临时有事没去。"),
        _task("阅读 30 页", duration=30, priority="low",
              goal_name=goal_read, tag="阅读", done=True, actual_minutes=35,
              note="读完了第 3 章。"),
    ]
    upsert_record(
        date=d1,
        tasks=tasks_d1,
        result="学习线持续推进，健身掉了一次。",
        status="一般",
        top_priority="完成学习章节 B 的概念 summary。",
        tomorrow_suggestion="明天继续推进学习章节 C，并把健身补回来。",
        suggestion_tracking={
            "source_date": d2,
            "source_top_priority": "完成学习章节 A 的练习题并对难点做笔记。",
            "source_tomorrow": "明天上午把学习章节 B 的核心概念写成一页 summary。",
            "status": "done",
            "reason": "今天的完成项包含 '学习章节 B 概念 summary'，与昨日建议方向一致。",
            "auto_judged": True,
            "confidence": "high",
            "hit_count": 4,
        },
        ai_plan_result={
            "overall": "学习线被守住，健身作为次线风险较低。",
            "covers_focus": "覆盖了当前阶段重点。",
            "issues": [],
            "focus_tasks": ["学习章节 B 概念 summary"],
            "adjustments": ["如果下午精力好，可以提前把 summary 扩成 PPT。"],
            "time_assessment": "适中。",
            "top_priority": "完成学习章节 B 的概念 summary。",
            "degraded": False,
        },
        ai_review_result={
            "score": "完成度良好，核心线连续推进。",
            "real_progress": "学习章节 B 的 summary 写完，阅读也推进了一章。",
            "weak_lines": "健身今天缺席，但属于单日波动，不必立刻强提醒。",
            "tomorrow": "明天继续推进学习章节 C，并把健身补回来。",
            "focus_insight": "学习任务低估 17%，可以把下一个同类任务的预估从 90 分钟调到 80 分钟。",
            "degraded": False,
        },
    )

    # --- Day 0 (today): plan only, no review yet -------------------------
    tasks_d0 = [
        _task("学习章节 C 新概念", duration=90, priority="high",
              goal_name=goal_study, tag="学习", done=False, must=True),
        _task("健身房力量训练（补上昨天）", duration=60, priority="medium",
              goal_name=goal_gym, tag="健身", done=False),
        _task("阅读 20 页", duration=20, priority="low",
              goal_name=goal_read, tag="阅读", done=False),
    ]
    upsert_record(
        date=d0,
        tasks=tasks_d0,
        plan="今天继续推进学习主线，同时把昨天缺席的健身补回来。",
        status="一般",
    )

    return {
        "status": "seeded",
        "goals": len(goals),
        "records": 3,
        "dates": [d2, d1, d0],
    }
