"""验证异步请求与双路检索的并发行为。"""

import asyncio
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.knowledge import web_api
from app.knowledge.local_repository import LocalRepository
from app.knowledge.milvus_repository import MilvusRepository
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


class AsyncKnowledgeTests(unittest.IsolatedAsyncioTestCase):
    """验证异步链路不改变结果，且阻塞任务不会占住事件循环。"""

    async def test_async_answer_matches_sync_answer(self) -> None:
        """异步决策循环保留冲突证据及状态。"""
        path = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"
        service = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(path)))
        expected = await asyncio.to_thread(service.ask, "报销期限多久？")
        result = await service.ask_async("报销期限多久？")
        self.assertEqual(result, expected)
        self.assertEqual(result["status"], "needs_clarification")

    async def test_async_model_is_awaited(self) -> None:
        """模型提供异步接口时，问答使用该接口而不是同步调用。"""
        class AsyncModel:
            """只允许异步决策的测试模型。"""

            def decide(self, question: str, history: list, trace: list) -> dict:
                """错误地使用同步接口时明确失败。"""
                raise AssertionError("不应调用同步模型")

            async def decide_async(self, question: str, history: list, trace: list) -> dict:
                """异步返回资料不足的结束动作。"""
                await asyncio.sleep(0)
                return {"action": "finish", "status": "insufficient", "answer": "资料不足", "citations": []}

        path = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"
        service = KnowledgeService(AsyncModel(), KnowledgeTools(LocalRepository(path)))
        result = await service.ask_async("不存在的问题")
        self.assertEqual(result["status"], "insufficient")

    async def test_import_creation_does_not_block_other_requests(self) -> None:
        """创建任务等待数据库时，事件循环仍能响应其他请求。"""
        started, release = threading.Event(), threading.Event()

        def slow_create(*args: object) -> dict:
            """模拟等待外部服务的同步任务创建。"""
            started.set()
            if not release.wait(3):
                raise TimeoutError("测试未释放任务")
            return {"id": "test-task"}

        transport = httpx.ASGITransport(app=web_api.app)
        with patch.object(web_api.importer, "create", side_effect=slow_create), \
             patch.object(web_api.importer, "process"):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                upload = asyncio.create_task(client.post("/api/import", files={"file": ("x.txt", b"test")},
                                                          data={"version_date": "2026-01-01"}))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    response = await asyncio.wait_for(client.get("/api/import/missing"), timeout=1)
                    self.assertEqual(response.status_code, 404)
                finally:
                    release.set()
                self.assertEqual((await upload).status_code, 202)

    async def test_direct_search_overlaps_hyde_generation(self) -> None:
        """两路工作交错执行且先固定版本快照。"""
        repository = object.__new__(MilvusRepository)
        started, hyde_started = threading.Event(), threading.Event()
        snapshot = threading.Event()

        def freeze() -> dict:
            """记录快照已固定。"""
            snapshot.set()
            return {}

        def search(query: str) -> list:
            """让普通检索等待 HyDE 开始，确认两者并发。"""
            self.assertTrue(snapshot.is_set())
            if query == "问题":
                started.set()
                if not hyde_started.wait(2):
                    raise TimeoutError("HyDE 未并发启动")
            return []

        def hyde(query: str) -> str:
            """等待普通检索启动并解除其等待。"""
            if not started.wait(2):
                raise TimeoutError("普通检索未并发启动")
            hyde_started.set()
            return "假设文档"

        with patch.object(repository, "_active_snapshot", side_effect=freeze), \
             patch.object(repository, "_search", side_effect=search), \
             patch("app.knowledge.milvus_repository._create_hyde", side_effect=hyde):
            self.assertEqual(await repository.search_async("问题"), [])


if __name__ == "__main__":
    unittest.main()
