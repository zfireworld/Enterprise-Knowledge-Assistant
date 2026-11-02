"""驱动模型、工具和证据校验。"""

from typing import Any

from app.knowledge.model import DecisionModel
from app.knowledge.tools import KnowledgeTools


class KnowledgeService:
    """在调用上限内执行决策循环，并校验最终引用。"""

    def __init__(self, model: DecisionModel, tools: KnowledgeTools, max_calls: int = 8) -> None:
        """设置 model、tools 与工具调用上限；无效上限抛出 ValueError。"""
        if max_calls < 1:
            raise ValueError("工具调用上限必须大于零")
        self.model, self.tools, self.max_calls = model, tools, max_calls

    def ask(self, question: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """处理问题及可选历史，返回答案、状态、引用和执行轨迹。"""
        if not question.strip():
            raise ValueError("问题不能为空")
        self.tools.evidence.clear()
        trace: list[dict[str, Any]] = []
        for _ in range(self.max_calls + 1):
            try:
                decision = self.model.decide(question, history or [], trace)
                if decision.get("action") == "finish":
                    return self._finish(decision, trace)
                if len(trace) >= self.max_calls:
                    break
                trace.append(self._execute(decision))
            except Exception as exc:
                return self._incomplete(f"模型或决策执行失败：{exc}", trace)
        return self._incomplete("达到工具调用上限", trace)

    def _execute(self, decision: dict[str, Any]) -> dict[str, Any]:
        """执行模型选择的工具并记录输入和结果；工具异常保留为观察结果。"""
        action = decision.get("action")
        entry = {"action": action, "reason": decision.get("reason", "")}
        try:
            if action == "search_documents":
                entry["arguments"] = {"query": decision["query"]}
                entry["result"] = self.tools.search_documents(**entry["arguments"])
            elif action == "read_passage":
                entry["arguments"] = {"doc_id": decision["doc_id"], "chunk_id": decision["chunk_id"]}
                entry["result"] = self.tools.read_passage(**entry["arguments"])
            else:
                raise ValueError(f"不支持的动作：{action}")
        except Exception as exc:
            entry["error"] = str(exc)
        return entry

    def _finish(self, decision: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """校验证据并生成结果；无效证据返回未完成状态。"""
        status = decision.get("status")
        citations = decision.get("citations", [])
        if status not in {"completed", "needs_clarification", "insufficient", "incomplete"}:
            return self._incomplete("模型返回无效状态", trace)
        if any(entry.get("error") for entry in trace):
            return self._incomplete("工具失败，无法确认回答完整", trace)
        if status == "completed" and not citations:
            return self._incomplete("回答缺少引用", trace)
        checked = []
        for citation in citations:
            passage = self.tools.evidence.get((citation.get("doc_id"), citation.get("chunk_id")))
            quote = citation.get("quote", "")
            if not passage or not quote or quote not in passage.text:
                return self._incomplete("引用不属于已读取原文", trace)
            checked.append({**citation, "version_date": passage.version_date})
        return {"status": status, "answer": decision.get("answer", ""), "citations": checked,
                "missing_information": decision.get("missing_information", ""), "trace": trace,
                "decision_reason": decision.get("reason", "")}

    def _incomplete(self, reason: str, trace: list[dict[str, Any]]) -> dict[str, Any]:
        """返回未完成状态，保留 reason 和已执行轨迹。"""
        return {"status": "incomplete", "answer": reason, "citations": [], "missing_information": reason, "trace": trace}
