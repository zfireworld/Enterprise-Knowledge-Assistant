"""使用 LangChain 模型生成下一步动作。"""

import json
from typing import Any, Protocol


class DecisionModel(Protocol):
    """决策模型接口：接收问题、历史及工具轨迹，返回下一动作。"""

    def decide(self, question: str, history: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """根据已有观察返回结构化动作；模型调用失败时抛出异常。"""
        ...


class LangChainDecisionModel:
    """复用项目的 LangChain 模型客户端，要求输出结构化 JSON。"""

    def __init__(self) -> None:
        """初始化项目已有模型客户端；配置错误时抛出异常。"""
        from app.lm.lm_utils import get_llm_client
        self.client = get_llm_client(json_mode=True)

    def decide(self, question: str, history: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        """调用模型选择下一动作；无效 JSON 或模型异常向上传递。"""
        prompt = (
            "你是企业知识问答助手。根据问题、历史和工具结果选择下一步，输出一个JSON对象。"
            "动作格式：{\"action\":\"search_documents\",\"query\":\"检索词\",\"reason\":\"简短依据\"}；"
            "{\"action\":\"read_passage\",\"doc_id\":\"文档ID\",\"chunk_id\":\"片段ID\",\"reason\":\"依据\"}；"
            "或{\"action\":\"finish\",\"status\":\"completed|needs_clarification|insufficient|incomplete\","
            "\"answer\":\"回答\",\"missing_information\":\"缺口\",\"citations\":[{\"doc_id\":\"ID\","
            "\"chunk_id\":\"ID\",\"quote\":\"原文子串\"}],\"reason\":\"依据\"}。"
            "先搜索并读取相关原文。发现可能冲突时搜索并读取各方，缺少优先级时说明冲突并追问。"
            "不得根据日期新旧、检索排名或一般惯例推断哪份制度优先，也不得暗示某一规则更可能适用；"
            "只有原文明确规定优先级或适用范围才能引用该依据作判断。"
            "不要用假设内容作为证据，不得编造引用；资料不足或工具失败时明确说明。"
        )
        payload = json.dumps({"question": question, "history": history, "trace": trace}, ensure_ascii=False)
        response = self.client.invoke([("system", prompt), ("human", payload)])
        return json.loads(response.content)
