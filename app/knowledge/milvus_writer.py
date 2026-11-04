"""将知识文档及 BGE 向量写入 Milvus。"""

from typing import Any

from app.knowledge.domain import Passage
from app.knowledge.milvus_repository import MilvusRepository


class MilvusWriter:
    """使用查询所配置的 Milvus 集合导入文档片段。"""

    def __init__(self) -> None:
        """连接已配置的集合。"""
        self.repository = MilvusRepository()

    def insert(self, passages: list[Passage]) -> None:
        """生成稠密和稀疏向量并插入集合，失败则抛出异常。"""
        from app.lm.embedding_utils import generate_embeddings
        from app.import_process.agent.nodes.node_import_milvus import create_collection
        records = []
        # 限制单批输入数量，避免长文档在 CPU 上一次占用过多内存。
        for start in range(0, len(passages), 5):
            batch = passages[start:start + 5]
            vectors = generate_embeddings([f"{item.title}\n{item.text}" for item in batch])
            records.extend(self._record(item, vectors, index) for index, item in enumerate(batch))
        client, collection = self.repository.client, self.repository.collection
        if not client.has_collection(collection_name=collection):
            create_collection(client, collection, len(records[0]["dense_vector"]))
        result = client.insert(collection_name=collection, data=records)
        if len(result.get("ids", [])) != len(records):
            raise RuntimeError("Milvus 返回的插入数量与片段数量不一致")
        client.flush(collection_name=collection)

    def _record(self, item: Passage, vectors: dict[str, Any], index: int) -> dict[str, Any]:
        """将片段与对应的两种向量组装为 Milvus 行。"""
        record = {"doc_id": item.doc_id, "version_id": item.version_id, "version_date": item.version_date, "title": item.title,
                "parent_title": item.title, "part": 0, "file_title": item.title, "item_name": "",
                "content": item.text, "dense_vector": vectors["dense"][index],
                "sparse_vector": vectors["sparse"][index]}
        if item.page_number is not None:
            record["page_number"] = item.page_number
        return record
