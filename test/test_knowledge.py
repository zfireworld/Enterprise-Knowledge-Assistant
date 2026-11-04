"""覆盖知识问答关键流程。"""

import json
import tempfile
import unittest
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


class KnowledgeTests(unittest.TestCase):
    """验证引用、冲突、上下文及错误处理。"""

    def setUp(self) -> None:
        """加载项目合成资料，供每个用例独立运行。"""
        self.path = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"
        self.service = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(self.path)))

    def test_conflict(self) -> None:
        """冲突应引用双方并请求澄清。"""
        result = self.service.ask("报销期限多久？")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual({item["doc_id"] for item in result["citations"]}, {"D01", "D02"})

    def test_normal_and_rewrite(self) -> None:
        """相似问题应返回同一文档的原文。"""
        first = self.service.ask("忘记登录密码怎么办？")
        second = self.service.ask("账号密码如何重置？")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["citations"], second["citations"])

    def test_missing_and_history(self) -> None:
        """资料外问题与历史追问返回不同状态。"""
        self.assertEqual(self.service.ask("公司停车位收费吗？")["status"], "insufficient")
        result = self.service.ask("有几天？", [{"role": "user", "content": "年假怎么规定？"}])
        self.assertEqual(result["citations"][0]["doc_id"], "D04")

    def test_tool_failure_and_limit(self) -> None:
        """知识库故障和调用上限均应返回未完成。"""
        broken = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(Path("missing.json"))))
        self.assertEqual(broken.ask("报销多久？")["status"], "incomplete")
        limited = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(self.path)), 1)
        self.assertEqual(limited.ask("报销多久？")["status"], "incomplete")

    def test_changed_document_is_used(self) -> None:
        """替换原文后，答案和引用应随之变化。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            records = json.loads(self.path.read_text(encoding="utf-8"))
            records[2]["text"] = "员工应联系服务台重置登录密码。"
            path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            result = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(path))).ask("忘记登录密码怎么办？")
            self.assertIn("服务台", result["answer"])
            self.assertIn("服务台", result["citations"][0]["quote"])

    def test_rejects_unread_citation(self) -> None:
        """没有读取原文时，不能接受模型虚构的引用。"""
        class UntrustedModel:
            """返回未经验证引用的测试模型。"""

            def decide(self, question: str, history: list, trace: list) -> dict:
                """忽略输入，返回虚构引用。"""
                return {"action": "finish", "status": "completed", "answer": "30天",
                        "citations": [{"doc_id": "D01", "chunk_id": "D01-1", "quote": "30天"}]}

        result = KnowledgeService(UntrustedModel(), KnowledgeTools(LocalRepository(self.path))).ask("报销多久？")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(sum(item["action"] == "citation_validation" for item in result["trace"]), 2)

    def test_revises_citation_against_read_passage(self) -> None:
        """错误引用反馈给模型后，只接受逐字匹配的原文。"""
        class CorrectingModel:
            """先返回错误引用，再根据校验反馈修正。"""

            def decide(self, question: str, history: list, trace: list) -> dict:
                """根据轨迹模拟读取、错误引用和修正。"""
                if not trace:
                    return {"action": "read_passage", "doc_id": "D03", "chunk_id": "D03-1"}
                quote = "内部账号平台" if any(item["action"] == "citation_validation" for item in trace) else "内部平台"
                return {"action": "finish", "status": "completed", "answer": "通过内部账号平台重置。",
                        "citations": [{"doc_id": "D03", "chunk_id": "D03-1", "quote": quote}]}

        result = KnowledgeService(CorrectingModel(), KnowledgeTools(LocalRepository(self.path)), 1).ask("如何重置密码？")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["citations"][0]["quote"], "内部账号平台")
        self.assertEqual([item["action"] for item in result["trace"]], ["read_passage", "budget_notice", "citation_validation"])
        self.assertEqual(result["trace"][-1]["problems"][0]["reason"], "引用文字不是该片段中的连续原文")

    def test_citation_whitespace_uses_original_text(self) -> None:
        """空白差异可匹配，但返回的引用必须取自源文本。"""
        source = "操作步骤：\n\n装入烫金膜。"
        self.assertEqual(self.service._match_quote("操作步骤： 装入烫金膜。", source), source)
        self.assertEqual(self.service._match_quote("操作步骤： 装入纸张。", source), "")


if __name__ == "__main__":
    unittest.main()
