"""知识片段与工具协议。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Passage:
    """可追溯的文档片段：文档、版本、片段标识及原文。"""

    doc_id: str
    version_date: str
    chunk_id: str
    title: str
    text: str


class Repository(Protocol):
    """知识库接口，读取或检索失败时抛出异常。"""

    def search(self, query: str) -> list[Passage]:
        """根据 query 查找候选片段；返回候选列表。"""
        ...

    def read(self, doc_id: str, chunk_id: str) -> Passage:
        """根据文档及片段标识读取原文；不存在时抛出 LookupError。"""
        ...
