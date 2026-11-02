"""生成离线模式的实际输入、输出及执行轨迹。"""

import json
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


def main() -> None:
    """运行三个示例并将输入及输出写入 examples 目录。"""
    root = Path(__file__).resolve().parents[1]
    cases = {"normal": ("账号密码如何重置？", root / "data/knowledge.json"),
             "conflict": ("报销期限多久？", root / "data/knowledge.json"),
             "missing": ("公司停车位收费吗？", root / "data/knowledge.json"),
             "tool_failure": ("报销期限多久？", root / "data/nonexistent.json")}
    for name, (question, data_path) in cases.items():
        service = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(data_path)))
        result = service.ask(question)
        payload = {"input": {"question": question, "data": str(data_path.relative_to(root))}, "output": result}
        (root / "examples" / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
