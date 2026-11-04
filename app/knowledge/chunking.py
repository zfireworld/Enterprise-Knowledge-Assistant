"""将知识文档切分为带上下文重叠的原文片段。"""

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


@lru_cache(maxsize=1)
def _splitter() -> "RecursiveCharacterTextSplitter":
    """创建并缓存递归切分器；依赖不可用时抛出 ImportError。"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", ". ", " ", ""],
        keep_separator="end",
        strip_whitespace=False,
    )


def split_text(text: str) -> list[str]:
    """切分原文并返回有序片段；空文本返回空列表。"""
    if not text or not text.strip():
        return []
    return _splitter().split_text(text)
