from threading import RLock
from typing import Any

from FlagEmbedding import FlagReranker
from app.conf.reranker_config import reranker_config

_reranker_model = None
_reranker_lock = RLock()

def get_reranker_model() -> Any:
    """获取共享的重排序模型；初始化失败时异常向上传递。"""
    global _reranker_model
    with _reranker_lock:
        if _reranker_model is None:
            _reranker_model = FlagReranker(
                model_name_or_path=reranker_config.bge_reranker_large,
                device=reranker_config.bge_reranker_device,
                use_fp16=reranker_config.bge_reranker_fp16
            )
        return _reranker_model


def rank_pairs(pairs: list[list[str]]) -> Any:
    """对问题和片段批量评分，串行使用共享模型；失败时抛出异常。"""
    with _reranker_lock:
        return get_reranker_model().compute_score(pairs)
