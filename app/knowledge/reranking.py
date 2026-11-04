"""复用 BGE 重排序与原有动态 Top-K 保留策略。"""

import math
from collections.abc import Iterable
from numbers import Real
from typing import Any

from app.core.logger import logger


def rerank_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对完整片段打分并按原有阈值截断；模型失败时返回原顺序。"""
    if not candidates:
        return []
    try:
        from app.lm.reranker_utils import rank_pairs
        from app.query_process.agent.nodes.node_rerank import step_3_topk
        pairs = [[query, str(item.get("content") or "")] for item in candidates]
        raw = rank_pairs(pairs)
        scores = [raw] if isinstance(raw, Real) or not isinstance(raw, Iterable) else list(raw)
        if len(scores) != len(candidates):
            raise ValueError("重排序分数数量与候选数量不一致")
        numeric = [float(score) for score in scores]
        if not all(math.isfinite(score) for score in numeric):
            raise ValueError("重排序分数不是有效数值")
        # 保留原始字段，避免旧重排节点的格式转换覆盖文档 ID 和版本。
        ranked = [{**item, "score": score} for item, score in zip(candidates, numeric)]
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return step_3_topk(ranked)
    except Exception as exc:
        logger.warning(f"知识问答重排序失败，回退 RRF 顺序：{type(exc).__name__}: {exc}")
        return candidates
