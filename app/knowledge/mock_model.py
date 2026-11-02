"""确定性离线模型，用于演示流程而非证明模型决策能力。"""

from typing import Any


class MockDecisionModel:
    """按观察结果执行固定策略，生成与真实模型相同的动作结构。"""

    def decide(self, question: str, history: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """根据 question、history 和 trace 决定下一动作；返回动作字典。"""
        if not trace:
            context = " ".join(str(item.get("content", "")) for item in history)
            return {"action": "search_documents", "query": f"{context} {question}".strip(), "reason": "查找相关资料"}
        if any(item.get("error") for item in trace):
            return {"action": "finish", "status": "incomplete", "answer": "工具失败，无法核实资料。", "missing_information": "工具结果", "citations": [], "reason": "工具不可用"}
        results = [entry["result"] for entry in trace if entry["action"] == "search_documents"]
        candidates = results[-1] if results else []
        read_ids = {(entry["result"]["doc_id"], entry["result"]["chunk_id"]) for entry in trace if entry["action"] == "read_passage"}
        for item in candidates:
            if (item["doc_id"], item["chunk_id"]) not in read_ids:
                return {"action": "read_passage", "doc_id": item["doc_id"], "chunk_id": item["chunk_id"], "reason": "核对候选原文"}
        return self._finish(trace)

    def _finish(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        """根据 trace 中已读原文生成离线结果；返回结束动作。"""
        passages = [entry["result"] for entry in trace if entry["action"] == "read_passage"]
        if not passages:
            return {"action": "finish", "status": "insufficient", "answer": "未找到相关资料。", "missing_information": "相关制度", "citations": [], "reason": "检索无结果"}
        citations = [{"doc_id": item["doc_id"], "chunk_id": item["chunk_id"], "quote": item["text"]} for item in passages]
        if len({item["doc_id"] for item in passages}) > 1:
            answer = "资料存在不同规定：" + "；".join(item["text"] for item in passages) + "请确认适用制度。"
            return {"action": "finish", "status": "needs_clarification", "answer": answer, "missing_information": "适用范围或优先级", "citations": citations, "reason": "多份资料需要核对"}
        return {"action": "finish", "status": "completed", "answer": "\n".join(item["text"] for item in passages), "missing_information": "", "citations": citations, "reason": "已有原文依据"}
