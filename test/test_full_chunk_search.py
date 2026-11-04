"""验证完整片段检索与独立读取证据的边界。"""

import unittest
from typing import Any

from app.knowledge.domain import Passage
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools

TEXT = "设备背景说明。" * 30 + "首次开机请连接电源适配器。"
PASSAGE = Passage("D01", "2025-01-01", "D01-1", "设备指南", TEXT, "v1")


class FakeRepository:
    """提供一条含长正文的候选记录。"""

    def search(self, query: str) -> list[Passage]:
        """返回包含后半段答案的片段。"""
        return [PASSAGE]

    def read(self, doc_id: str, chunk_id: str) -> Passage:
        """验证片段标识并返回原文。"""
        if (doc_id, chunk_id) != (PASSAGE.doc_id, PASSAGE.chunk_id):
            raise LookupError("片段不存在")
        return PASSAGE


class SearchThenFinishModel:
    """模拟看过完整搜索结果后直接引用的模型。"""

    def decide(self, question: str, history: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """先搜索，再尝试引用末尾但不读取原文。"""
        if not trace:
            return {"action": "search_documents", "query": question}
        return {"action": "finish", "status": "completed", "answer": "连接电源",
                "citations": [{"doc_id": "D01", "chunk_id": "D01-1", "quote": "首次开机请连接电源适配器。"}]}


class SearchThenReadModel(SearchThenFinishModel):
    """模拟看到搜索结果后先读取再引用的模型。"""

    def decide(self, question: str, history: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """看到末尾答案后读取该片段，然后生成引用。"""
        if not trace:
            return {"action": "search_documents", "query": question}
        if trace[-1]["action"] == "search_documents":
            if "首次开机请连接电源适配器。" not in trace[-1]["result"][0]["text"]:
                return {"action": "finish", "status": "insufficient", "citations": []}
            return {"action": "read_passage", "doc_id": "D01", "chunk_id": "D01-1"}
        return super().decide(question, history, trace)


class FullChunkSearchTests(unittest.TestCase):
    """覆盖同步搜索和读取校验。"""

    def test_search_returns_full_text_but_does_not_register_evidence(self) -> None:
        """搜索可看到 160 字之后的内容，但不能直接引用。"""
        tools = KnowledgeTools(FakeRepository())
        self.assertEqual(tools.search_documents("如何开机")[0]["text"], TEXT)
        self.assertEqual(tools.evidence, {})
        result = KnowledgeService(SearchThenFinishModel(), tools).ask("如何开机")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["citation_problems"][0]["reason"], "该片段尚未读取")

    def test_search_then_read_allows_verified_quote(self) -> None:
        """模型依据完整候选选择读取，读取后的引用可通过校验。"""
        result = KnowledgeService(SearchThenReadModel(), KnowledgeTools(FakeRepository())).ask("如何开机")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["citations"][0]["quote"], "首次开机请连接电源适配器。")
        self.assertEqual([step["action"] for step in result["trace"]], ["search_documents", "read_passage"])


class AsyncFullChunkSearchTests(unittest.IsolatedAsyncioTestCase):
    """覆盖网页使用的异步搜索。"""

    async def test_async_returns_full_text_without_evidence(self) -> None:
        """异步搜索返回全文，读取动作才登记证据。"""
        tools = KnowledgeTools(FakeRepository())
        self.assertEqual((await tools.search_documents_async("如何开机"))[0]["text"], TEXT)
        self.assertEqual(tools.evidence, {})
        tools.read_passage("D01", "D01-1")
        self.assertEqual(tools.evidence[("D01", "D01-1")], PASSAGE)


if __name__ == "__main__":
    unittest.main()
