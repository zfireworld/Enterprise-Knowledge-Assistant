"""调用已配置的真实模型，记录两条实际决策轨迹。"""

import json
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.model import LangChainDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


def main() -> None:
    """执行真实模型案例并保存结果；服务不可用时结果包含失败状态。"""
    root = Path(__file__).resolve().parents[1]
    model = LangChainDecisionModel()
    for name, question in (("real_normal", "账号密码如何重置？"), ("real_conflict", "报销期限多久？")):
        service = KnowledgeService(model, KnowledgeTools(LocalRepository(root / "data/knowledge.json")))
        result = service.ask(question)
        (root / "examples" / f"{name}.json").write_text(
            json.dumps({"input": {"question": question}, "output": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{name}: {result['status']}, calls={len(result['trace'])}")


if __name__ == "__main__":
    main()
