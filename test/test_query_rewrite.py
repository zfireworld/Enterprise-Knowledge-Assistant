"""覆盖上下文追问改写和失败回退。"""

import json
import unittest
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.query_rewrite import parse_rewrite, rewrite_messages
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools

HISTORY = [{"role": "user", "content": "h 怎么用"},
           {"role": "assistant", "content": "请确认是 HAK 180 还是 HUAWEI MateBook B3-420？"}]


class RewriteModel:
    """记录 Agent 收到的问题，并模拟改写与结束动作。"""

    def __init__(self, failed: bool = False) -> None:
        """设置是否模拟改写失败。"""
        self.failed = failed
        self.received = None
        self.rewrite_calls = 0

    def rewrite(self, question: str, history: list[dict]) -> str:
        """模拟模型结合上下文改写或抛出异常。"""
        self.rewrite_calls += 1
        if self.failed:
            raise RuntimeError("模型不可用")
        return "HUAWEI MateBook B3-420 怎么用？"

    async def rewrite_async(self, question: str, history: list[dict]) -> str:
        """异步返回相同的改写结果。"""
        return self.rewrite(question, history)

    def decide(self, question: str, history: list[dict], trace: list[dict]) -> dict:
        """记录输入并返回资料不足。"""
        self.received = (question, history)
        return {"action": "finish", "status": "insufficient", "answer": "资料不足", "citations": []}


class QueryRewriteTests(unittest.TestCase):
    """验证同步改写及上下文限制。"""

    def setUp(self) -> None:
        """准备不访问外部服务的工具。"""
        self.tools = KnowledgeTools(LocalRepository(Path("data/knowledge.json")))

    def test_clarification_becomes_standalone_question(self) -> None:
        """用户只回答产品名时，Agent 接收结合原需求的改写问题。"""
        model = RewriteModel()
        result = KnowledgeService(model, self.tools).ask("HUAWEI MateBook B3-420", HISTORY)
        self.assertEqual(model.received, ("HUAWEI MateBook B3-420 怎么用？", HISTORY))
        self.assertEqual(result["query_rewrite"]["original"], "HUAWEI MateBook B3-420")
        self.assertEqual(result["query_rewrite"]["status"], "completed")

    def test_failure_falls_back_without_losing_history(self) -> None:
        """改写失败时保留原问题及历史，仍可继续决策。"""
        model = RewriteModel(failed=True)
        result = KnowledgeService(model, self.tools).ask("HUAWEI MateBook B3-420", HISTORY)
        self.assertEqual(model.received, ("HUAWEI MateBook B3-420", HISTORY))
        self.assertEqual(result["query_rewrite"]["status"], "failed")

    def test_no_history_skips_rewrite(self) -> None:
        """首次提问不增加模型调用。"""
        model = RewriteModel()
        result = KnowledgeService(model, self.tools).ask("年假几天？")
        self.assertEqual(model.rewrite_calls, 0)
        self.assertEqual(result["query_rewrite"]["status"], "skipped")

    def test_rewrite_history_is_bounded_and_invalid_output_rejected(self) -> None:
        """改写请求仅使用最近六条消息，并拒绝空结果。"""
        history = [{"role": "user", "content": str(index)} for index in range(10)]
        payload = json.loads(rewrite_messages("问题", history)[1][1])
        self.assertEqual([item["content"] for item in payload["history"]], list(map(str, range(4, 10))))
        with self.assertRaises(ValueError):
            parse_rewrite('{"question":" "}')


class AsyncQueryRewriteTests(unittest.IsolatedAsyncioTestCase):
    """验证异步网页路径使用相同的改写与回退逻辑。"""

    async def test_async_rewrite_and_failure(self) -> None:
        """异步改写成功和失败时均传递正确问题及历史。"""
        tools = KnowledgeTools(LocalRepository(Path("data/knowledge.json")))
        model = RewriteModel()
        result = await KnowledgeService(model, tools).ask_async("HUAWEI MateBook B3-420", HISTORY)
        self.assertEqual(model.received, ("HUAWEI MateBook B3-420 怎么用？", HISTORY))
        self.assertEqual(result["query_rewrite"]["status"], "completed")
        model = RewriteModel(failed=True)
        result = await KnowledgeService(model, tools).ask_async("HUAWEI MateBook B3-420", HISTORY)
        self.assertEqual(model.received, ("HUAWEI MateBook B3-420", HISTORY))
        self.assertEqual(result["query_rewrite"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
