"""知识检索与原文读取工具。"""

from dataclasses import asdict
from typing import Any

from app.knowledge.domain import Passage, Repository


class KnowledgeTools:
    """包装 repository，保留已读取的证据用于引用校验。"""

    def __init__(self, repository: Repository) -> None:
        """初始化知识库和本次运行的证据集合。"""
        self.repository = repository
        self.evidence: dict[tuple[str, str], Passage] = {}

    def search_documents(self, query: str) -> list[dict[str, Any]]:
        """用 query 搜索候选文档；返回带标识和摘要的列表，错误向上传递。"""
        if not query.strip():
            raise ValueError("检索词不能为空")
        return [{**asdict(item), "text": item.text[:160]} for item in self.repository.search(query)]

    def read_passage(self, doc_id: str, chunk_id: str) -> dict[str, Any]:
        """读取指定文档片段；返回原文，不存在时抛出异常。"""
        item = self.repository.read(doc_id, chunk_id)
        self.evidence[(item.doc_id, item.chunk_id)] = item
        return asdict(item)
