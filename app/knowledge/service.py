"""驱动模型、工具和证据校验。"""

import asyncio
import re
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
        """同步入口：处理问题和历史；异步调用方应使用 ask_async。"""
        if not question.strip():
            raise ValueError("问题不能为空")
        self.tools.evidence.clear()
        trace: list[dict[str, Any]] = []
        tool_calls = citation_retries = 0
        budget_notified = False
        for _ in range(self.max_calls + 3):
            try:
                if tool_calls >= self.max_calls and not budget_notified:
                    trace.append({"action": "budget_notice", "result": "工具调用额度已用完，请仅根据已读取原文结束；证据不足时说明缺口。"})
                    budget_notified = True
                decision = self.model.decide(question, history or [], trace)
                if decision.get("action") == "finish":
                    result = self._finish(decision, trace)
                    if result["answer"] == "引用不属于已读取原文" and citation_retries < 2:
                        citation_retries += 1
                        trace.append({"action": "citation_validation", "result": "引用校验失败。未读取的片段须先读取；其他引用须从对应片段逐字复制连续原文。若不能查证，请删除相关结论并说明缺口。", "problems": result["citation_problems"]})
                        continue
                    return result
                if tool_calls >= self.max_calls:
                    break
                trace.append(self._execute(decision))
                tool_calls += 1
            except Exception as exc:
                return self._incomplete(f"模型或决策执行失败：{exc}", trace)
        return self._incomplete("达到工具调用上限", trace)

    async def ask_async(self, question: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """异步处理问题和历史，返回答案、状态、引用及轨迹。"""
        if not question.strip():
            raise ValueError("问题不能为空")
        self.tools.evidence.clear()
        trace: list[dict[str, Any]] = []
        tool_calls = 0
        citation_retries = 0
        budget_notified = False
        # 格式修正不消耗工具调用额度，但必须有单独上限。
        for _ in range(self.max_calls + 3):
            try:
                if tool_calls >= self.max_calls and not budget_notified:
                    trace.append({"action": "budget_notice", "result": "工具调用额度已用完，请仅根据已读取原文结束；证据不足时说明缺口。"})
                    budget_notified = True
                decide_async = getattr(self.model, "decide_async", None)
                if decide_async is not None:
                    decision = await decide_async(question, history or [], trace)
                else:
                    decision = await asyncio.to_thread(self.model.decide, question, history or [], trace)
                if decision.get("action") == "finish":
                    result = self._finish(decision, trace)
                    if result["answer"] == "引用不属于已读取原文" and citation_retries < 2:
                        citation_retries += 1
                        trace.append({"action": "citation_validation", "result": "引用校验失败。未读取的片段须先读取；其他引用须从对应片段逐字复制连续原文。若不能查证，请删除相关结论并说明缺口。", "problems": result["citation_problems"]})
                        continue
                    return result
                if tool_calls >= self.max_calls:
                    break
                trace.append(await self._execute_async(decision))
                tool_calls += 1
            except Exception as exc:
                return self._incomplete(f"模型或决策执行失败：{exc}", trace)
        return self._incomplete("达到工具调用上限", trace)

    async def _execute_async(self, decision: dict[str, Any]) -> dict[str, Any]:
        """异步执行检索；其他同步工具在线程中执行并保留错误观察。"""
        if decision.get("action") != "search_documents":
            return await asyncio.to_thread(self._execute, decision)
        entry: dict[str, Any] = {"action": "search_documents", "reason": decision.get("reason", "")}
        try:
            entry["arguments"] = {"query": decision["query"]}
            entry["result"] = await self.tools.search_documents_async(**entry["arguments"])
        except Exception as exc:
            entry["error"] = str(exc)
        return entry

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
        problems = []
        for citation in citations:
            doc_id = str(citation.get("doc_id", ""))
            chunk_id = str(citation.get("chunk_id", ""))
            passage = self.tools.evidence.get((doc_id, chunk_id))
            quote = citation.get("quote", "")
            if not passage:
                problems.append({"doc_id": doc_id, "chunk_id": chunk_id, "reason": "该片段尚未读取"})
                continue
            matched_quote = self._match_quote(quote, passage.text)
            if not matched_quote:
                problems.append({"doc_id": doc_id, "chunk_id": chunk_id, "reason": "引用文字不是该片段中的连续原文"})
                continue
            checked.append({**citation, "doc_id": doc_id, "chunk_id": chunk_id, "quote": matched_quote,
                            "version_date": passage.version_date, "version_id": passage.version_id})
        if problems:
            result = self._incomplete("引用不属于已读取原文", trace)
            result["citation_problems"] = problems
            return result
        return {"status": status, "answer": decision.get("answer", ""), "citations": checked,
                "missing_information": decision.get("missing_information", ""), "trace": trace,
                "decision_reason": decision.get("reason", "")}

    def _incomplete(self, reason: str, trace: list[dict[str, Any]]) -> dict[str, Any]:
        """返回未完成状态，保留 reason 和已执行轨迹。"""
        return {"status": "incomplete", "answer": reason, "citations": [], "missing_information": reason, "trace": trace}

    def _match_quote(self, quote: Any, source: str) -> str:
        """匹配原文，允许空白字符差异并返回源文本中的精确片段。"""
        if not isinstance(quote, str) or not quote.strip():
            return ""
        if quote in source:
            return quote
        # PDF 转换产生的换行和空格可能被模型合并，返回值仍取自原文。
        parts = re.split(r"(\s+)", quote.strip())
        pattern = "".join(r"\s+" if part.isspace() else re.escape(part) for part in parts)
        match = re.search(pattern, source)
        return match.group() if match else ""
