"""Three-tier task auto-tagging.

Tier 1 · User-supplied tag wins (``auto_source="manual"``).
Tier 2 · Keyword match against ``DOMAIN_HINTS`` from task_inference_service.
Tier 3 · Embedding cosine against per-tag centroids learned from history.
Tier 4 · Fallback — ``"突发"`` when ``is_unplanned``, else ``"其他"``.

The service returns a dict ``{tag, auto_source, confidence, reason}``. The UI
uses ``auto_source`` to color-code the tag badge and ``reason`` as tooltip.
"""

from __future__ import annotations

from services.llm_service import embed_texts
from services.task_inference_service import (
    DOMAIN_HINTS,
    _cosine_similarity,
    _extract_tokens,
)


UNPLANNED_TAG = "突发"
FALLBACK_TAG = "其他"
EMBEDDING_THRESHOLD = 0.55

# Extra synonyms layered on top of DOMAIN_HINTS for classification.
# Keep this narrow: only add high-precision variants, not generic verbs.
EXTRA_HINTS = {
    "健身": {"晨跑", "夜跑", "训练", "撸铁", "瑜伽", "器械", "深蹲", "俯卧撑"},
    "英语": {"雅思", "托福", "背词", "朗读"},
    "论文": {"开题", "答辩", "汇报", "综述", "5.3", "5.4"},
    "课程": {"网课", "线上课", "讲座"},
    "实习": {"投递", "笔试", "hr", "oa"},
}


def _combined_hints(tag: str) -> set[str]:
    base = set(DOMAIN_HINTS.get(tag, set()))
    base |= EXTRA_HINTS.get(tag, set())
    return base


def _manual_result(user_tag: str) -> dict:
    return {
        "tag": user_tag,
        "auto_source": "manual",
        "confidence": 1.0,
        "reason": "用户手动指定",
    }


def _keyword_match(task_text: str, known_tags: list[str]) -> dict | None:
    tokens = _extract_tokens(task_text)
    text_lower = task_text.lower()
    compact = text_lower.replace(" ", "")

    best_tag = ""
    best_overlap = 0
    best_hits: list[str] = []

    # First try DOMAIN_HINTS keys (well-curated clusters) — these are always candidates
    candidate_tags = set(DOMAIN_HINTS.keys()) | {str(t).strip() for t in known_tags if str(t).strip()}

    for tag in candidate_tags:
        hints = _combined_hints(tag) | {tag.lower()}
        hits = [hint for hint in hints if hint and (hint in compact or hint in text_lower or hint in tokens)]
        if not hits:
            continue
        if len(hits) > best_overlap:
            best_tag = tag
            best_overlap = len(hits)
            best_hits = hits

    if not best_tag:
        return None
    return {
        "tag": best_tag,
        "auto_source": "keyword",
        "confidence": 0.85,
        "reason": f"命中关键词：{'、'.join(best_hits[:3])}",
    }


def _build_tag_centroids(
    historical_tasks: list[dict],
    known_tags: list[str],
) -> dict[str, list[float]]:
    """Average embedding across historical tasks per tag."""
    tag_to_texts: dict[str, list[str]] = {}
    known_set = {str(t).strip() for t in known_tags if str(t).strip()}
    for task in historical_tasks:
        tag = str(task.get("tag") or "").strip()
        text = str(task.get("text") or "").strip()
        if not tag or not text:
            continue
        if known_set and tag not in known_set:
            continue
        tag_to_texts.setdefault(tag, []).append(text)

    if not tag_to_texts:
        return {}

    flat_texts: list[str] = []
    index_of: dict[str, list[int]] = {}
    for tag, texts in tag_to_texts.items():
        for text in texts:
            index_of.setdefault(tag, []).append(len(flat_texts))
            flat_texts.append(text)

    embeddings = embed_texts(flat_texts)
    if not embeddings or not any(embeddings):
        return {}

    centroids: dict[str, list[float]] = {}
    for tag, indices in index_of.items():
        vectors = [embeddings[i] for i in indices if i < len(embeddings) and embeddings[i]]
        if not vectors:
            continue
        dim = len(vectors[0])
        summed = [0.0] * dim
        for vec in vectors:
            if len(vec) != dim:
                continue
            for i in range(dim):
                summed[i] += vec[i]
        centroids[tag] = [value / len(vectors) for value in summed]
    return centroids


def _embedding_match(
    task_text: str,
    historical_tasks: list[dict],
    known_tags: list[str],
) -> dict | None:
    centroids = _build_tag_centroids(historical_tasks, known_tags)
    if not centroids:
        return None

    task_embeddings = embed_texts([task_text])
    if not task_embeddings or not task_embeddings[0]:
        return None
    task_vec = task_embeddings[0]

    ranked = []
    for tag, centroid in centroids.items():
        similarity = (_cosine_similarity(task_vec, centroid) + 1) / 2
        ranked.append((tag, similarity))
    if not ranked:
        return None

    ranked.sort(key=lambda item: item[1], reverse=True)
    best_tag, best_sim = ranked[0]
    if best_sim < EMBEDDING_THRESHOLD:
        return None

    return {
        "tag": best_tag,
        "auto_source": "embedding",
        "confidence": round(best_sim, 3),
        "reason": f"与历史 '{best_tag}' 任务语义相似度 {best_sim:.2f}",
    }


def classify_task_tag(
    task_text: str,
    user_tag: str | None = "",
    historical_tasks: list[dict] | None = None,
    known_tags: list[str] | None = None,
    is_unplanned: bool = False,
) -> dict:
    """Classify a task into a tag using a four-tier pipeline.

    Returns a dict with keys ``tag``, ``auto_source``, ``confidence``, ``reason``.
    """
    task_text = str(task_text or "").strip()
    user_tag = str(user_tag or "").strip()
    historical_tasks = historical_tasks or []
    known_tags = known_tags or []

    if user_tag:
        return _manual_result(user_tag)

    if not task_text:
        return {
            "tag": UNPLANNED_TAG if is_unplanned else FALLBACK_TAG,
            "auto_source": "unplanned" if is_unplanned else "fallback",
            "confidence": 0.0,
            "reason": "任务文本为空",
        }

    keyword_hit = _keyword_match(task_text, known_tags)
    if keyword_hit:
        return keyword_hit

    embedding_hit = _embedding_match(task_text, historical_tasks, known_tags)
    if embedding_hit:
        return embedding_hit

    if is_unplanned:
        return {
            "tag": UNPLANNED_TAG,
            "auto_source": "unplanned",
            "confidence": 0.0,
            "reason": "计划外新增任务，标记为突发",
        }

    return {
        "tag": FALLBACK_TAG,
        "auto_source": "fallback",
        "confidence": 0.0,
        "reason": "无匹配的关键词或历史语义相似项",
    }
