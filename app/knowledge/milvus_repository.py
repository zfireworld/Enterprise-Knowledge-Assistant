"""复用 BGE、Milvus 和 RRF 的双路知识检索。"""

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any

from app.knowledge.domain import Passage
from app.knowledge.reranking import rerank_candidates

if TYPE_CHECKING:
    from app.knowledge.version_repository import VersionRepository


def _create_hyde(query: str) -> str:
    """在线程中加载 HyDE 组件并生成假设文档，异常向上传递。"""
    from app.query_process.agent.nodes.node_search_embedding_hyde import step_1_create_hyde_doc
    return step_1_create_hyde_doc(query)


def _merge_results(direct: list[dict[str, Any]], hyde: list[dict[str, Any]]) -> list:
    """在线程中加载 RRF 组件并融合两路候选结果。"""
    from app.query_process.agent.nodes.node_rrf import reciprocal_rank_fusion
    return reciprocal_rank_fusion([(direct, 1.0), (hyde, 1.0)], max_results=10)


class MilvusRepository:
    """使用已有集合；要求数据包含文档 ID、版本日期和原文。"""

    def __init__(self) -> None:
        """获取 Milvus 客户端与集合名；配置不可用时抛出 RuntimeError。"""
        from app.clients.milvus_utils import get_milvus_client
        self.client = get_milvus_client()
        self.collection = os.getenv("CHUNKS_COLLECTION", "")
        if self.client is None or not self.collection:
            raise RuntimeError("Milvus 连接或 CHUNKS_COLLECTION 未配置")
        self._snapshot: dict[str, str | None] | None = None

    def _version_store(self) -> "VersionRepository":
        """创建当前向量集合对应的版本仓库。"""
        from app.knowledge.version_repository import VersionRepository
        return VersionRepository(self.collection)

    def _active_snapshot(self) -> dict[str, str | None]:
        """冻结本次请求的当前版本；MongoDB 失败时不执行查询。"""
        if self._snapshot is None:
            self._snapshot = {doc["doc_id"]: doc.get("current_version")
                              for doc in self._version_store().list_documents()}
        return self._snapshot

    def _version_filter(self) -> str:
        """构造当前版本过滤条件；未登记的旧数据按旧版处理。"""
        snapshot = self._active_snapshot()
        active = [(doc, version) for doc, version in snapshot.items() if version and version != "legacy"]
        excluded = [doc for doc, version in snapshot.items() if version != "legacy"]
        legacy = '(not exists $meta["version_id"])'
        if excluded:
            legacy += f' and doc_id not in {json.dumps(excluded, ensure_ascii=True)}'
        branches = [f"({legacy})"]
        for doc_id, version_id in active:
            branches.append(f'(doc_id == {json.dumps(doc_id)} and version_id == {json.dumps(version_id)})')
        # 动态字段缺失时，仅用 != 空字符串不足以可靠排除旧记录。
        required = '(exists $meta["doc_id"]) and (exists $meta["version_date"])'
        return required + ' and doc_id != "" and version_date != "" and (' + " or ".join(branches) + ")"

    def _search(self, text: str) -> list[dict[str, Any]]:
        """以 text 执行稠密和稀疏混合检索；服务异常向上传递。"""
        from app.clients.milvus_utils import create_hybrid_search_requests, hybrid_search
        from app.lm.embedding_utils import generate_embeddings
        from app.query_process.agent.nodes.node_rrf import _as_entity_list
        vectors = generate_embeddings([text])
        requests = create_hybrid_search_requests(vectors["dense"][0], vectors["sparse"][0],
                                                  expr=self._version_filter(), limit=10)
        results = hybrid_search(self.client, self.collection, requests, limit=10,
                                output_fields=["doc_id", "version_id", "version_date", "chunk_id", "content", "title"])
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
        ranked = rerank_candidates(query, [item for item, _ in merged])
        return [self._passage(item) for item in ranked]

    async def search_async(self, query: str) -> list[Passage]:
        """并发执行普通召回和 HyDE 生成，再合并两路检索结果。"""
        # 先固定版本，避免两个分支跨版本切换读取到不同快照。
        await asyncio.to_thread(self._active_snapshot)
        direct, hypothetical = await asyncio.gather(
            asyncio.to_thread(self._search, query),
            asyncio.to_thread(_create_hyde, query),
        )
        hyde = await asyncio.to_thread(self._search, f"{query} {hypothetical}")
        merged = await asyncio.to_thread(_merge_results, direct, hyde)
        ranked = await asyncio.to_thread(rerank_candidates, query, [item for item, _ in merged])
        return [self._passage(item) for item in ranked]

    def read(self, doc_id: str, chunk_id: str) -> Passage:
        """按 Milvus 主键读取并验证文档归属；缺失时抛出 LookupError。"""
        records = self.client.get(collection_name=self.collection, ids=[int(chunk_id)],
                                  output_fields=["doc_id", "version_id", "version_date", "chunk_id", "content", "title"])
        if not records:
            raise LookupError(f"片段不存在：{doc_id}/{chunk_id}")
        passage = self._passage(records[0])
        if passage.doc_id != doc_id:
            raise LookupError("片段与文档 ID 不匹配")
        expected = self._active_snapshot().get(doc_id, "legacy")
        if (passage.version_id or "legacy") != expected:
            raise LookupError("片段不属于本次查询的当前版本")
        return passage

    def list_documents(self) -> list[dict[str, Any]]:
        """列出集合中最多 1000 个片段所属的文档。"""
        managed = self._version_store().list_documents()
        documents = {doc["doc_id"]: self._document_summary(doc) for doc in managed if doc.get("current_version")}
        for item in self.list_legacy_documents():
            if item["doc_id"] not in {doc["doc_id"] for doc in managed}:
                documents[item["doc_id"]] = item
        return list(documents.values())

    def list_legacy_documents(self) -> list[dict[str, Any]]:
        """列出尚无 version_id 的旧文档，供展示和登记。"""
        if not self.client.has_collection(collection_name=self.collection):
            return []
        records = self.client.query(collection_name=self.collection,
            filter='chunk_id >= 0 and (exists $meta["doc_id"]) and (exists $meta["version_date"]) '
                   'and doc_id != "" and version_date != "" and not exists $meta["version_id"]',
            limit=1000, output_fields=["doc_id", "version_date", "title"])
        documents: dict[str, dict[str, Any]] = {}
        for item in records:
            if not item.get("doc_id") or not item.get("version_date"):
                continue
            entry = documents.setdefault(item["doc_id"], {"doc_id": item["doc_id"],
                      "title": item.get("title", ""), "version_date": item["version_date"],
                      "version_id": "legacy", "version_number": 1, "chunks": 0})
            entry["chunks"] += 1
        return list(documents.values())

    def _document_summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        """从版本记录提取当前版本的页面摘要。"""
        version = next(item for item in doc["versions"] if item["version_id"] == doc["current_version"])
        return {"doc_id": doc["doc_id"], "title": doc["title"], "version_id": version["version_id"],
                "version_number": version["number"], "version_date": version["version_date"], "chunks": version["chunks"]}

    def _passage(self, item: dict[str, Any]) -> Passage:
        """将 Milvus 记录转换为片段；缺少文档或版本信息时抛出 ValueError。"""
        if not item.get("doc_id") or not item.get("version_date"):
            raise ValueError("Milvus 片段缺少 doc_id 或 version_date，需补充元数据并重新导入")
        return Passage(str(item["doc_id"]), str(item["version_date"]), str(item.get("chunk_id", item.get("id"))),
                       str(item.get("title", "")), str(item.get("content", "")), str(item.get("version_id") or ""))
