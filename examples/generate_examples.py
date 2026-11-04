"""生成离线模式的实际输入、输出及执行轨迹。"""

import json
from pathlib import Path

from app.knowledge.local_repository import LocalRepository
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools


def main() -> None:
    """运行离线案例并记录实际输入、结果和工具轨迹；应从仓库根目录执行。"""
    root = Path(__file__).resolve().parents[1]
    cases = {
        "normal": ("忘记登录密码怎么办？", "data/knowledge.json", []),
        "rewrite": ("账号密码如何重置？", "data/knowledge.json", []),
        "conflict": ("报销期限多久？", "data/knowledge.json", []),
        "missing": ("公司停车位收费吗？", "data/knowledge.json", []),
        "history": ("有几天？", "data/knowledge.json", [{"role": "user", "content": "年假怎么规定？"}]),
        "tool_failure": ("报销期限多久？", "data/nonexistent.json", []),
        "changed_document": ("忘记登录密码怎么办？", "data/knowledge_updated.json", []),
    }
    for name, (question, data_path, history) in cases.items():
        # 使用相对路径让故障轨迹可复现，并避免写入本机用户名。
        service = KnowledgeService(MockDecisionModel(), KnowledgeTools(LocalRepository(Path(data_path))))
        result = service.ask(question, history)
        payload = {"mode": "offline_mock_local_repository", "input": {"question": question,
                   "history": history, "data": data_path}, "output": result}
        (root / "examples" / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {result['status']}, trace={len(result['trace'])}")


if __name__ == "__main__":
    main()
