"""验证页面 API 与导入、查询的集成。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.knowledge import web_api
from app.knowledge.import_service import ImportService


class FakeRepository:
    """用于测试的内存向量库替身。"""

    passages = []

    def search(self, query: str) -> list:
        """返回测试中导入的片段。"""
        return self.passages

    def read(self, doc_id: str, chunk_id: str) -> object:
        """按标识返回测试片段。"""
        return next(item for item in self.passages if item.doc_id == doc_id and item.chunk_id == chunk_id)

    def list_documents(self) -> list[dict]:
        """返回测试片段对应的文档。"""
        return [{"doc_id": item.doc_id, "title": item.title, "version_date": item.version_date, "chunks": 1}
                for item in self.passages]


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
        self.repository = patch("app.knowledge.milvus_repository.MilvusRepository", FakeRepository)
        self.writer = patch("app.knowledge.milvus_writer.MilvusWriter", FakeWriter)
        self.importer = patch.object(web_api, "importer", ImportService(Path(self.temp.name)))
        for mock in (self.repository, self.writer, self.importer):
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


if __name__ == "__main__":
    unittest.main()
