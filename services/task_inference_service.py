from __future__ import annotations

import math
import re

from services.llm_service import embed_texts

DOMAIN_HINTS = {
    "英语": {"单词", "背单词", "词汇", "阅读", "听力", "翻译", "写作", "口语", "六级", "四级", "四六级", "cet"},
    "论文": {"论文", "文献", "paper", "科研", "实验", "投稿", "导师", "综述"},
    "实习": {"实习", "项目", "简历", "面试", "八股", "算法", "开发", "技术栈", "秋招", "暑期"},
    "健身": {"健身", "跑步", "游泳", "有氧", "力量", "减脂", "增肌", "体能"},
    "课程": {"上课", "作业", "课程", "考试", "复习", "期末", "实验课"},
}


def _extract_tokens(text: str) -> set[str]:
    content = str(text or "").strip().lower()
    if not content:
        return set()

    tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{2,}", content))
    compact = re.sub(r"\s+", "", content)
    tokens.update(
        compact[index : index + 2]
        for index in range(len(compact) - 1)
    )
    return {token for token in tokens if token.strip()}


def _expand_goal_tokens(goal: dict) -> set[str]:
    signature = " ".join(
        [
            str(goal.get("goal", "")).strip(),
            str(goal.get("description", "")).strip(),
            " ".join(goal.get("tags", [])),
        ]
    )
    tokens = _extract_tokens(signature)

    signature_lower = signature.lower()
    for key, hints in DOMAIN_HINTS.items():
        if key in signature or key.lower() in signature_lower or any(hint in signature_lower for hint in hints):
            tokens.update(hints)
    return tokens


def _goal_signature(goal: dict) -> str:
    parts = [
        str(goal.get("goal", "")).strip(),
        str(goal.get("description", "")).strip(),
        " ".join(goal.get("tags", [])),
        " ".join(sorted(_expand_goal_tokens(goal))),
    ]
    return " ".join(part for part in parts if part)


def _task_signature(task_text: str, task_tag: str = "") -> str:
    return " ".join(part for part in [str(task_text).strip(), str(task_tag).strip()] if part)


def _keyword_overlap_score(task_tokens: set[str], goal_tokens: set[str]) -> float:
    if not task_tokens or not goal_tokens:
        return 0.0
    overlap = task_tokens & goal_tokens
    return len(overlap) / max(min(len(task_tokens), 6), 1)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def infer_goal_for_task(goals: list[dict], task_text: str, task_tag: str = "") -> dict | None:
    text = str(task_text or "").strip()
    if not goals or not text:
        return None

    goal_signatures = [_goal_signature(goal) for goal in goals]
    embeddings = embed_texts([_task_signature(text, task_tag), *goal_signatures])
    task_embedding = embeddings[0] if embeddings else []
    task_tokens = _extract_tokens(_task_signature(text, task_tag))

    ranked = []
    for index, goal in enumerate(goals, start=1):
        goal_tokens = _expand_goal_tokens(goal)
        overlap_score = _keyword_overlap_score(task_tokens, goal_tokens)
        semantic_score = (_cosine_similarity(task_embedding, embeddings[index]) + 1) / 2 if task_embedding else 0.0

        exact_tag_bonus = 0.0
        if task_tag and any(task_tag.strip().lower() == str(tag).strip().lower() for tag in goal.get("tags", [])):
            exact_tag_bonus = 0.12

        total_score = semantic_score * 0.55 + overlap_score * 0.45 + exact_tag_bonus
        ranked.append(
            {
                "goal": goal,
                "score": round(total_score, 4),
                "semantic_score": round(semantic_score, 4),
                "overlap_score": round(overlap_score, 4),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = best["score"] - (second["score"] if second else 0.0)

    if best["score"] < 0.42 and not (best["overlap_score"] >= 0.34 and best["semantic_score"] >= 0.45):
        return None
    if second and best["score"] < 0.62 and margin < 0.06:
        return None

    matched_goal = best["goal"]
    return {
        "goal": matched_goal.get("goal", ""),
        "goal_id": matched_goal.get("goal_id", ""),
        "score": best["score"],
        "semantic_score": best["semantic_score"],
        "overlap_score": best["overlap_score"],
        "source": "auto",
    }


def auto_link_tasks(goals: list[dict], tasks: list[dict], keep_existing: bool = True) -> list[dict]:
    linked_tasks = []
    for task in tasks:
        current = dict(task)
        has_existing = bool(current.get("goal_id") or current.get("goal"))
        if keep_existing and has_existing:
            linked_tasks.append(current)
            continue

        match = infer_goal_for_task(goals, current.get("text", ""), current.get("tag", ""))
        if match:
            current["goal"] = match["goal"]
            current["goal_id"] = match["goal_id"]
            current["goal_source"] = match["source"]
        else:
            current["goal"] = ""
            current["goal_id"] = ""
            current.pop("goal_source", None)
        linked_tasks.append(current)
    return linked_tasks
