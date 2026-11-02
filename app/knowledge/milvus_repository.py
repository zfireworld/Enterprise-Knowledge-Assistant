"""复用 BGE、Milvus 和 RRF 的双路知识检索。"""

import os
from typing import Any

from app.knowledge.domain import Passage


class MilvusRepository:
    """使用已有集合；要求数据包含文档 ID、版本日期和原文。"""

    def __init__(self) -> None:
        """获取 Milvus 客户端与集合名；配置不可用时抛出 RuntimeError。"""
        from app.clients.milvus_utils import get_milvus_client
        self.client = get_milvus_client()
        self.collection = os.getenv("CHUNKS_COLLECTION", "")
        if self.client is None or not self.collection:
            raise RuntimeError("Milvus 连接或 CHUNKS_COLLECTION 未配置")

    def _search(self, text: str) -> list[dict[str, Any]]:
        """以 text 执行稠密和稀疏混合检索；服务异常向上传递。"""
        from app.clients.milvus_utils import create_hybrid_search_requests, hybrid_search
        from app.lm.embedding_utils import generate_embeddings
        from app.query_process.agent.nodes.node_rrf import _as_entity_list
        vectors = generate_embeddings([text])
        # 旧商品数据可能没有版本元数据，不能当作可引用的企业制度。
        requests = create_hybrid_search_requests(vectors["dense"][0], vectors["sparse"][0],
                                                  expr='doc_id != "" and version_date != ""', limit=10)
        results = hybrid_search(self.client, self.collection, requests, limit=10,
                                output_fields=["doc_id", "version_date", "chunk_id", "content", "title"])
        if results is None:
            raise RuntimeError("Milvus 混合检索失败")
        return _as_entity_list(results[0] if results else [])

    def search(self, query: str) -> list[Passage]:
        """以问题和 HyDE 假设文档分别召回，再以 RRF 合并；错误向上传递。"""
        from app.query_process.agent.nodes.node_rrf import reciprocal_rank_fusion
        from app.query_process.agent.nodes.node_search_embedding_hyde import step_1_create_hyde_doc
        direct = self._search(query)
        hypothetical = step_1_create_hyde_doc(query)
        hyde = self._search(f"{query} {hypothetical}")
        merged = reciprocal_rank_fusion([(direct, 1.0), (hyde, 1.0)], max_results=10)
        return [self._passage(item) for item, _ in merged]

    def read(self, doc_id: str, chunk_id: str) -> Passage:
        """按 Milvus 主键读取并验证文档归属；缺失时抛出 LookupError。"""
        records = self.client.get(collection_name=self.collection, ids=[int(chunk_id)],
                                  output_fields=["doc_id", "version_date", "chunk_id", "content", "title"])
        if not records:
            raise LookupError(f"片段不存在：{doc_id}/{chunk_id}")
        passage = self._passage(records[0])
        if passage.doc_id != doc_id:
            raise LookupError("片段与文档 ID 不匹配")
        return passage

    def list_documents(self) -> list[dict[str, Any]]:
        """列出集合中最多 1000 个片段所属的文档。"""
        if not self.client.has_collection(collection_name=self.collection):
            return []
        records = self.client.query(collection_name=self.collection,
                                    filter='chunk_id >= 0 and doc_id != "" and version_date != ""', limit=1000,
                                    output_fields=["doc_id", "version_date", "title"])
        documents: dict[str, dict[str, Any]] = {}
        for item in records:
            if not item.get("doc_id") or not item.get("version_date"):
                continue
            entry = documents.setdefault(item["doc_id"], {"doc_id": item["doc_id"],
                      "title": item.get("title", ""), "version_date": item["version_date"], "chunks": 0})
            entry["chunks"] += 1
        return list(documents.values())

    def _passage(self, item: dict[str, Any]) -> Passage:
        """将 Milvus 记录转换为片段；缺少文档或版本信息时抛出 ValueError。"""
        if not item.get("doc_id") or not item.get("version_date"):
            raise ValueError("Milvus 片段缺少 doc_id 或 version_date，需补充元数据并重新导入")
        return Passage(str(item["doc_id"]), str(item["version_date"]), str(item.get("chunk_id", item.get("id"))),
                       str(item.get("title", "")), str(item.get("content", "")))
