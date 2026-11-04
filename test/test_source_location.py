"""验证 PDF 页码、版本文件链接与来源校验。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.knowledge import web_api
from app.knowledge.domain import Passage
from app.knowledge.import_service import ImportService
from app.knowledge.milvus_repository import MilvusRepository
from app.knowledge.milvus_writer import MilvusWriter
from app.knowledge.pdf_chunks import split_pdf_pages
from app.knowledge.service import KnowledgeService
from app.knowledge.source_files import resolve_source, source_url
from app.knowledge.tools import KnowledgeTools


class FakeStore:
    """在内存中保存各版本的文件映射。"""

    def __init__(self, versions: list[dict]) -> None:
        """保存测试版本列表。"""
        self.versions = versions

    def get(self, doc_id: str) -> dict | None:
        """返回匹配的文档记录。"""
        return {"doc_id": doc_id, "versions": self.versions} if doc_id == "D01" else None


class SourceLocationTests(unittest.TestCase):
    """验证页码切分、文件访问和引用来源。"""

    def setUp(self) -> None:
        """创建相互隔离的版本文件。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "v1").mkdir()
        (self.root / "v2").mkdir()
        (self.root / "v1" / "guide.pdf").write_bytes(b"%PDF-version-one")
        (self.root / "v2" / "guide.pdf").write_bytes(b"%PDF-version-two")
        self.versions = [
            {"version_id": "v1", "status": "published", "source": {"storage_key": "v1/guide.pdf"}},
            {"version_id": "v2", "status": "published", "source": {"storage_key": "v2/guide.pdf"}},
        ]
        self.store = FakeStore(self.versions)

    def test_page_chunks_preserve_physical_pages_and_long_text(self) -> None:
        """页码从零转换为一，长文本切分后不跨页并保留表格和图片引用。"""
        path = self.root / "content_list.json"
        data = [{"type": "text", "text": "甲" * 900, "page_idx": 0},
                {"type": "table", "table_body": "<table>乙</table>", "page_idx": 1},
                {"type": "image", "img_path": "images/a.jpg", "image_caption": ["图示"], "page_idx": 1}]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        pages = split_pdf_pages(path)
        self.assertGreaterEqual(sum(page == 1 for page, _ in pages), 2)
        self.assertTrue(all("乙" not in text for page, text in pages if page == 1))
        self.assertIn("<table>乙</table>", "".join(text for page, text in pages if page == 2))
        self.assertIn("![](images/a.jpg)", "".join(text for page, text in pages if page == 2))

    def test_invalid_page_never_guesses(self) -> None:
        """带内容的块缺失页码时拒绝推断来源。"""
        path = self.root / "bad.json"
        path.write_text('[{"type":"text","text":"内容"}]', encoding="utf-8")
        with self.assertRaises(ValueError):
            split_pdf_pages(path)

    def test_version_file_endpoint_and_unsafe_paths(self) -> None:
        """文件接口返回指定的历史版本，并拒绝缺失、未发布和越界路径。"""
        importer = ImportService(self.root)
        with patch.object(web_api, "importer", importer), patch.object(importer, "_store", return_value=self.store):
            client = TestClient(web_api.app)
            response = client.get("/api/documents/D01/versions/v1/file")
            self.assertEqual(response.content, b"%PDF-version-one")
            self.assertTrue(response.headers["content-type"].startswith("application/pdf"))
            self.assertIn("inline", response.headers["content-disposition"])
            self.assertEqual(client.get("/api/documents/D01/versions/v2/file").content, b"%PDF-version-two")
            self.assertEqual(client.get("/api/documents/D01/versions/unknown/file").status_code, 404)
            self.versions[0]["status"] = "failed"
            self.assertEqual(client.get("/api/documents/D01/versions/v1/file").status_code, 404)
        with self.assertRaises(FileNotFoundError):
            resolve_source(self.root, {"status": "published", "source": {"storage_key": "../outside.pdf"}})

    def test_milvus_read_attaches_source_only_for_matching_published_version(self) -> None:
        """读取时使用文档、版本、页码生成来源；旧版本缺失则不生成链接。"""
        class Client:
            """返回模拟的 Milvus 记录。"""

            def get(self, **kwargs: object) -> list[dict]:
                """返回可引用的 PDF 第二页。"""
                return [{"doc_id": "D01", "version_id": "v1", "version_date": "2025-01-01",
                         "chunk_id": 123, "title": "指南", "content": "第二页内容", "page_number": 2}]

        repository = object.__new__(MilvusRepository)
        repository.client, repository.collection, repository._snapshot = Client(), "test", {"D01": "v1"}
        with patch.object(repository, "_version_store", return_value=self.store), \
             patch("app.knowledge.milvus_repository.SOURCE_ROOT", self.root):
            passage = repository.read("D01", "123")
            self.assertEqual(passage.source_url, "/api/documents/D01/versions/v1/file#page=2")
            self.assertEqual(passage.page_number, 2)
            self.versions[0].pop("source")
            self.assertEqual(repository.read("D01", "123").source_url, "")

    def test_citation_uses_verified_passage_not_model_url(self) -> None:
        """最终引用只能携带读取工具返回的页码和链接。"""
        tools = KnowledgeTools(object())
        tools.evidence[("D01", "1")] = Passage("D01", "2025-01-01", "1", "标题", "真实原文", "v1", 2,
                                               source_url("D01", "v1", 2))
        service = KnowledgeService(object(), tools)
        result = service._finish({"status": "completed", "citations": [{"doc_id": "D01", "chunk_id": "1",
                  "quote": "真实原文", "page_number": 99, "source_url": "https://invalid.example"}]}, [])
        self.assertEqual(result["citations"][0]["page_number"], 2)
        self.assertEqual(result["citations"][0]["source_url"], "/api/documents/D01/versions/v1/file#page=2")

    def test_milvus_record_has_page_only_when_known(self) -> None:
        """写入记录在有页码时保留字段，未知时不编造。"""
        writer = object.__new__(MilvusWriter)
        vectors = {"dense": [[0.1]], "sparse": [{1: 1.0}]}
        known = Passage("D01", "2025-01-01", "1", "标题", "内容", "v1", 2)
        unknown = Passage("D01", "2025-01-01", "2", "标题", "内容", "v1")
        self.assertEqual(writer._record(known, vectors, 0)["page_number"], 2)
        self.assertNotIn("page_number", writer._record(unknown, vectors, 0))


if __name__ == "__main__":
    unittest.main()
