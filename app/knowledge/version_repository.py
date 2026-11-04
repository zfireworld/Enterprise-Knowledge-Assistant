"""持久化文档版本及当前版本指针。"""

import os
import uuid
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument

load_dotenv()

@lru_cache(maxsize=1)
def _mongo_client() -> MongoClient:
    """创建并复用配置的 MongoDB 客户端；缺少地址时抛出异常。"""
    url = os.getenv("MONGO_URL")
    if not url:
        raise RuntimeError("未配置 MONGO_URL")
    return MongoClient(url, serverSelectionTimeoutMS=5000)


class VersionRepository:
    """以 MongoDB 单文档原子操作维护各文档的版本。"""

    def __init__(self, collection_name: str) -> None:
        """绑定 MongoDB 元数据集合，并按 Milvus 集合隔离文档。"""
        database = os.getenv("MONGO_DB_NAME")
        if not database:
            raise RuntimeError("未配置 MONGO_DB_NAME")
        self.collection = _mongo_client()[database]["knowledge_document_versions"]
        self.namespace = collection_name

    def _key(self, doc_id: str) -> str:
        """生成当前集合内文档的唯一主键。"""
        return f"{self.namespace}:{doc_id}"

    def list_documents(self) -> list[dict[str, Any]]:
        """返回本集合的文档记录，含当前版本及版本历史。"""
        return list(self.collection.find({"namespace": self.namespace}, {"_id": 0}))

    def get(self, doc_id: str) -> dict[str, Any] | None:
        """读取指定文档，未找到时返回 None。"""
        return self.collection.find_one({"_id": self._key(doc_id)}, {"_id": 0})

    def register_legacy(self, document: dict[str, Any]) -> None:
        """将无版本标识的已有文档登记为 V1；已有记录不变。"""
        doc_id = document["doc_id"]
        legacy = {"version_id": "legacy", "number": 1, "version_date": document["version_date"],
                  "status": "published", "chunks": document["chunks"]}
        self.collection.update_one({"_id": self._key(doc_id)}, {"$setOnInsert": {
            "namespace": self.namespace, "doc_id": doc_id, "title": document["title"],
            "current_version": "legacy", "version_counter": 1, "versions": [legacy]}}, upsert=True)

    def reserve(self, doc_id: str, title: str, version_date: str, new_document: bool) -> dict[str, Any]:
        """为新建或更新预留独立版本；竞争更新时重试，失败抛出异常。"""
        if new_document:
            self.collection.insert_one({"_id": self._key(doc_id), "namespace": self.namespace,
                "doc_id": doc_id, "title": title, "current_version": None,
                "version_counter": 0, "versions": []})
        for _ in range(5):
            document = self.get(doc_id)
            if document is None:
                raise LookupError("要更新的文档不存在")
            number = document["version_counter"] + 1
            entry = {"version_id": uuid.uuid4().hex, "number": number, "version_date": version_date,
                     "status": "processing", "chunks": 0, "expected_current": document["current_version"]}
            updated = self.collection.find_one_and_update(
                {"_id": self._key(doc_id), "version_counter": number - 1,
                 "current_version": document["current_version"]},
                {"$inc": {"version_counter": 1}, "$push": {"versions": entry}},
                return_document=ReturnDocument.AFTER)
            if updated:
                return entry
        raise RuntimeError("文档版本正在被其他任务更新，请重试")

    def publish(self, doc_id: str, version: dict[str, Any], chunks: int) -> None:
        """仅在当前版本未改变时发布；竞争或状态异常时抛出错误。"""
        updated = self.collection.update_one(
            {"_id": self._key(doc_id), "current_version": version["expected_current"],
             "versions": {"$elemMatch": {"version_id": version["version_id"], "status": "processing"}}},
            {"$set": {"current_version": version["version_id"], "versions.$.status": "published",
                      "versions.$.chunks": chunks}})
        if updated.modified_count != 1:
            raise RuntimeError("当前版本已被其他任务更新，新版本未发布")

    def fail(self, doc_id: str, version_id: str, error: str) -> None:
        """将未发布版本标为失败；已发布版本不会被改写。"""
        self.collection.update_one({"_id": self._key(doc_id),
            "versions": {"$elemMatch": {"version_id": version_id, "status": "processing"}}},
            {"$set": {"versions.$.status": "failed", "versions.$.error": error}})
