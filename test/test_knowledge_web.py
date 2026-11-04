"""验证页面 API 与导入、查询的集成。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.knowledge import web_api
from app.knowledge.import_service import ImportService


class FakeVersionStore:
    """在内存中模拟文档版本和当前版本指针。"""

    documents = {}

    def get(self, doc_id: str) -> dict | None:
        """返回指定文档。"""
        return self.documents.get(doc_id)

    def list_documents(self) -> list[dict]:
        """列出文档版本记录。"""
        return list(self.documents.values())

    def reserve(self, doc_id: str, title: str, version_date: str, new_document: bool) -> dict:
        """预留版本号和发布前的当前指针。"""
        if new_document:
            self.documents[doc_id] = {"doc_id": doc_id, "title": title, "current_version": None, "versions": []}
        doc = self.documents[doc_id]
        number = len(doc["versions"]) + 1
        version = {"version_id": f"{doc_id}-version-{number}", "number": number, "version_date": version_date,
                   "status": "processing", "chunks": 0, "expected_current": doc["current_version"]}
        doc["versions"].append(version)
        return version

    def publish(self, doc_id: str, version: dict, chunks: int) -> None:
        """检查指针并发布版本。"""
        doc = self.documents[doc_id]
        if doc["current_version"] != version["expected_current"]:
            raise RuntimeError("当前版本已被其他任务更新")
        version.update(status="published", chunks=chunks)
        doc["current_version"] = version["version_id"]

    def fail(self, doc_id: str, version_id: str, error: str) -> None:
        """记录失败版本。"""
        version = next(item for item in self.documents[doc_id]["versions"] if item["version_id"] == version_id)
        version.update(status="failed", error=error)


class FakeRepository:
    """用于测试的内存向量库替身。"""

    passages = []

    def __init__(self) -> None:
        """冻结查询时的版本指针。"""
        self.snapshot = {key: value["current_version"] for key, value in FakeVersionStore.documents.items()}

    def _version_store(self) -> FakeVersionStore:
        """返回测试版本仓库。"""
        return FakeVersionStore()

    def search(self, query: str) -> list:
        """返回测试中导入的片段。"""
        return [item for item in self.passages if self.snapshot.get(item.doc_id) == item.version_id]

    def read(self, doc_id: str, chunk_id: str) -> object:
        """按标识返回测试片段。"""
        return next(item for item in self.search("") if item.doc_id == doc_id and item.chunk_id == chunk_id)

    def list_documents(self) -> list[dict]:
        """返回测试片段对应的文档。"""
        return [{"doc_id": item.doc_id, "title": item.title, "version_date": item.version_date, "chunks": 1}
                for item in self.search("")]


class FakeWriter:
    """记录写入请求的测试替身。"""

    def insert(self, passages: list) -> None:
        """将测试片段写入内存。"""
        FakeRepository.passages.extend(passages)


class KnowledgeWebTests(unittest.TestCase):
    """验证文件导入与聊天使用同一知识库接口。"""

    def setUp(self) -> None:
        """隔离测试工作目录与 Milvus。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        FakeRepository.passages = []
        FakeVersionStore.documents = {}
        self.repository = patch("app.knowledge.milvus_repository.MilvusRepository", FakeRepository)
        self.writer = patch("app.knowledge.milvus_writer.MilvusWriter", FakeWriter)
        self.importer = patch.object(web_api, "importer", ImportService(Path(self.temp.name)))
        self.store = patch.object(ImportService, "_store", return_value=FakeVersionStore())
        for mock in (self.repository, self.writer, self.importer, self.store):
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(web_api.app)

    def test_import_then_chat(self) -> None:
        """上传文档后可查询到其原文和版本。"""
        upload = self.client.post("/api/import", files={"file": ("规则.txt", "设备借用期限为七天。".encode(), "text/plain")},
                                  data={"version_date": "2026-01-01"})
        self.assertEqual(upload.status_code, 202)
        task = self.client.get(f"/api/import/{upload.json()['id']}").json()
        self.assertEqual(task["status"], "completed")
        answer = self.client.post("/api/chat", json={"question": "设备借用几天？", "model": "mock"}).json()
        self.assertEqual(answer["status"], "completed")
        self.assertEqual(answer["citations"][0]["version_date"], "2026-01-01")
        self.assertIn("七天", answer["citations"][0]["quote"])

    def test_invalid_file(self) -> None:
        """拒绝不支持的文件格式。"""
        response = self.client.post("/api/import", files={"file": ("test.exe", b"x")},
                                    data={"version_date": "2026-01-01"})
        self.assertEqual(response.status_code, 400)

    def test_failed_index_is_reported(self) -> None:
        """向量入库异常时，导入任务必须显示失败。"""
        with patch.object(FakeWriter, "insert", side_effect=RuntimeError("向量库不可用")):
            response = self.client.post("/api/import", files={"file": ("规则.txt", b"test")},
                                        data={"version_date": "2026-01-01"})
        task = self.client.get(f"/api/import/{response.json()['id']}").json()
        self.assertEqual(task["status"], "failed")
        self.assertIn("向量库不可用", task["error"])

    def test_repository_failure(self) -> None:
        """知识库连接失败时返回明确的服务错误。"""
        with patch("app.knowledge.milvus_repository.MilvusRepository", side_effect=RuntimeError("连接失败")):
            response = self.client.get("/api/documents")
        self.assertEqual(response.status_code, 503)

    def test_update_keeps_document_id_and_selects_new_version(self) -> None:
        """更新后查询新内容，历史版本仍保留。"""
        first = self.client.post("/api/import", files={"file": ("规则.txt", "报销期限30天".encode())},
                                 data={"version_date": "2025-01-01"}).json()
        first_task = self.client.get(f"/api/import/{first['id']}").json()
        doc_id = first_task["doc_id"]
        second = self.client.post("/api/import", files={"file": ("新规则.txt", "报销期限15天".encode())},
                                  data={"version_date": "2025-02-01", "doc_id": doc_id}).json()
        second_task = self.client.get(f"/api/import/{second['id']}").json()
        self.assertEqual(second_task["doc_id"], doc_id)
        self.assertEqual(second_task["version_number"], 2)
        answer = self.client.post("/api/chat", json={"question": "报销期限？", "model": "mock"}).json()
        self.assertIn("15天", answer["answer"])
        self.assertNotIn("30天", answer["answer"])
        versions = self.client.get(f"/api/documents/{doc_id}/versions").json()
        self.assertEqual(len(versions["versions"]), 2)

    def test_failed_update_preserves_current(self) -> None:
        """更新入库失败时，原版本仍可查询。"""
        first = self.client.post("/api/import", files={"file": ("规则.txt", "报销期限30天".encode())},
                                 data={"version_date": "2025-01-01"}).json()
        doc_id = first["doc_id"]
        with patch.object(FakeWriter, "insert", side_effect=RuntimeError("写入失败")):
            second = self.client.post("/api/import", files={"file": ("规则.txt", "报销期限15天".encode())},
                                      data={"version_date": "2025-02-01", "doc_id": doc_id}).json()
        self.assertEqual(self.client.get(f"/api/import/{second['id']}").json()["status"], "failed")
        answer = self.client.post("/api/chat", json={"question": "报销期限？", "model": "mock"}).json()
        self.assertIn("30天", answer["answer"])
        self.assertEqual(self.client.get(f"/api/documents/{doc_id}/versions").json()["versions"][-1]["status"], "failed")

    def test_concurrent_updates_do_not_override_winner(self) -> None:
        """两个版本基于同一旧版本时，只允许先完成者发布。"""
        service = web_api.importer
        first = service.create("规则.txt", "期限30天".encode(), "2025-01-01")
        service.process(first["id"], "2025-01-01")
        doc_id = first["doc_id"]
        update_a = service.create("A.txt", "期限15天".encode(), "2025-02-01", doc_id)
        update_b = service.create("B.txt", "期限20天".encode(), "2025-03-01", doc_id)
        service.process(update_a["id"], "2025-02-01")
        service.process(update_b["id"], "2025-03-01")
        self.assertEqual(service.tasks[update_a["id"]]["status"], "completed")
        self.assertEqual(service.tasks[update_b["id"]]["status"], "failed")
        self.assertEqual(FakeVersionStore.documents[doc_id]["current_version"], update_a["version_id"])


if __name__ == "__main__":
    unittest.main()
