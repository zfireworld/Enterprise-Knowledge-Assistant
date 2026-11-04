"""执行离线回归并将真实测试输出保存到 examples。"""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """运行测试，记录退出码和输出；失败时以非零状态退出。"""
    root = Path(__file__).resolve().parents[1]
    modules = ["test.test_knowledge", "test.test_knowledge_web", "test.test_knowledge_chunking",
               "test.test_knowledge_async", "test.test_query_rewrite", "test.test_milvus_result_normalization",
               "test.test_task_events", "test.test_knowledge_reranking", "test.test_full_chunk_search"]
    command = [sys.executable, "-m", "unittest", *modules, "-v"]
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout + result.stderr).replace(str(root), "<repository>")
    header = f"Command: python -m unittest {' '.join(modules)} -v\nExit code: {result.returncode}\n\n"
    (root / "examples" / "test-results.txt").write_text(header + output, encoding="utf-8")
    print(f"Test exit code: {result.returncode}; results: examples/test-results.txt")
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
