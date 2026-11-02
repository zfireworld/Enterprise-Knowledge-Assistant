"""企业知识问答命令行入口。"""

import argparse
import json
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


def main() -> None:
    """读取命令行问题、配置模型和知识库，输出 JSON；参数错误由 argparse 报告。"""
    parser = argparse.ArgumentParser(description="企业知识问答 Agent")
    parser.add_argument("question", help="员工问题")
    parser.add_argument("--model", choices=("mock", "real"), default="mock")
    parser.add_argument("--repository", choices=("local", "milvus"), default="local")
    parser.add_argument("--data", type=Path, default=Path("data/knowledge.json"))
    parser.add_argument("--history", default="[]", help="历史消息的 JSON 数组，字段为 role 和 content")
    parser.add_argument("--max-calls", type=int, default=8)
    args = parser.parse_args()
    if args.model == "real":
        from app.knowledge.model import LangChainDecisionModel
        model = LangChainDecisionModel()
    else:
        model = MockDecisionModel()
    if args.repository == "milvus":
        from app.knowledge.milvus_repository import MilvusRepository
        repository = MilvusRepository()
    else:
        repository = LocalRepository(args.data)
    history = json.loads(args.history)
    if not isinstance(history, list):
        parser.error("history 必须是 JSON 数组")
    result = KnowledgeService(model, KnowledgeTools(repository), args.max_calls).ask(args.question, history)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
