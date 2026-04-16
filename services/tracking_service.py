import re


_STOPWORDS = frozenset(
    "的了是在为了以及不要先再做用和或与也还但并把被让去来从到就都已经"
    "可以能够这个那个什么怎么如何分钟小时今天明天后天优先建议任务安排"
)

_DONE_SIGNALS = ["完成", "做完", "整理完", "写完", "搞定", "已经做", "已经完成", "推进了"]
_PARTIAL_SIGNALS = ["部分", "还没", "没完成", "没做完", "只做了", "不太懂", "不够", "先做了", "还差"]


def _extract_tokens(text: str) -> set[str]:
    clean = re.sub(r"[^\u4e00-\u9fff]", " ", str(text or ""))
    words = {
        word for word in clean.split() if len(word) >= 2 and not all(char in _STOPWORDS for char in word)
    }
    chars = re.sub(r"\s+", "", clean)
    bigrams = {
        chars[index : index + 2]
        for index in range(len(chars) - 1)
        if chars[index] not in _STOPWORDS and chars[index + 1] not in _STOPWORDS
    }
    return words | bigrams


def _hit_score(tokens: set[str], target_text: str) -> tuple[float, list[str]]:
    if not tokens:
        return 0.0, []
    hits = sorted(token for token in tokens if token in target_text)
    return len(hits) / len(tokens), hits


def _task_text(task: dict, include_note: bool = True) -> str:
    parts = [
        task.get("text", ""),
        task.get("goal", ""),
        task.get("tag", ""),
    ]
    if include_note:
        parts.append(task.get("note", ""))
    return " ".join(part for part in parts if part).strip()


def auto_track_suggestion(yesterday_rec: dict, today_tasks: list, today_extra: str) -> dict | None:
    if not yesterday_rec:
        return None

    ai_review = yesterday_rec.get("ai_review_result", {})
    ai_plan = yesterday_rec.get("ai_plan_result", {})

    tomorrow_suggestion = (
        yesterday_rec.get("tomorrow_suggestion")
        or ai_review.get("tomorrow")
        or ""
    ).strip()
    top_priority = (
        yesterday_rec.get("top_priority")
        or ai_plan.get("top_priority")
        or ""
    ).strip()

    if not tomorrow_suggestion and not top_priority:
        return None

    suggestion_text = f"{tomorrow_suggestion} {top_priority}".strip()
    suggestion_tokens = _extract_tokens(suggestion_text)

    planned_tasks = " ".join(_task_text(task, include_note=False) for task in today_tasks)
    done_tasks = [task for task in today_tasks if task.get("done")]
    done_text = " ".join(_task_text(task, include_note=True) for task in done_tasks)
    today_full = f"{done_text} {today_extra or ''}".strip()

    done_score, done_hits = _hit_score(suggestion_tokens, today_full)
    planned_score, planned_hits = _hit_score(suggestion_tokens, planned_tasks)

    notes_text = " ".join(task.get("note", "") for task in done_tasks).lower()
    has_done_signal = any(signal in notes_text for signal in _DONE_SIGNALS)
    has_partial_signal = any(signal in notes_text for signal in _PARTIAL_SIGNALS)

    hits_preview = "、".join((done_hits or planned_hits)[:4])

    if done_score >= 0.4 and not has_partial_signal:
        reason = (
            f"今天的完成项与备注和昨日建议高度一致"
            + (f"（命中关键词：{hits_preview}）" if hits_preview else "")
        )
        if has_done_signal:
            reason += "，而且备注中出现了明确完成信号。"
        else:
            reason += "，可以判断这条建议已经被执行。"
        status = "done"
    elif done_score >= 0.2 or planned_score >= 0.3 or (done_score > 0 and has_partial_signal):
        fragments = []
        if planned_score >= 0.3 and planned_hits:
            fragments.append(f"今天的计划已经覆盖建议方向（命中：{'、'.join(planned_hits[:4])}）")
        if done_score > 0 and done_hits:
            fragments.append(f"完成记录与建议存在部分重合（命中：{'、'.join(done_hits[:4])}）")
        if has_partial_signal:
            fragments.append("但备注显示推进还不完整")
        if not fragments:
            fragments.append("今天和昨日建议存在弱相关，但完成证据不够充分")
        reason = "；".join(fragments) + "。"
        status = "partial"
    else:
        if planned_tasks:
            reason = (
                "今天的任务与昨日建议重合度较低，系统没有看到明确执行证据。"
                " 这可能说明临时任务打断了原定推进，或昨日建议不适合今天的实际节奏。"
            )
        else:
            reason = "今天缺少足够的计划或完成记录，系统无法判断昨日建议是否被执行。"
        status = "not_obvious"

    return {
        "source_date": yesterday_rec["date"],
        "source_top_priority": top_priority,
        "source_tomorrow": tomorrow_suggestion,
        "status": status,
        "reason": reason,
        "auto_judged": True,
    }


STATUS_LABEL = {
    "done": "已执行",
    "partial": "部分执行",
    "not_obvious": "未明显执行",
}

STATUS_COLOR = {
    "done": "#10B981",
    "partial": "#F59E0B",
    "not_obvious": "#9CA3AF",
}
