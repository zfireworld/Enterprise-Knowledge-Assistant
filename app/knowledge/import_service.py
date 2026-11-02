"""将上传文件转换为知识片段并保存到本地仓库。"""

import threading
import uuid
from pathlib import Path

from app.knowledge.domain import Passage


class ImportService:
    """管理单进程内的文件导入和任务状态。"""

    def __init__(self, work_dir: Path) -> None:
        """初始化工作目录和导入任务状态。"""
        self.work_dir = work_dir
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()

    def create(self, filename: str, content: bytes, version: str) -> dict:
        """创建任务并暂存文件；返回可供轮询的任务信息。"""
        task_id = uuid.uuid4().hex
        name = Path(filename.replace("\\", "/")).name
        self.tasks[task_id] = {"id": task_id, "filename": name, "status": "pending"}
        folder = self.work_dir / task_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        return self.tasks[task_id].copy()

    def process(self, task_id: str, version: str) -> None:
        """解析任务文件并保存片段；失败时记录明确错误。"""
        task = self.tasks[task_id]
        task["status"] = "processing"
        try:
            path = self.work_dir / task_id / task["filename"]
            text = self._read_text(path, task_id)
            passages = self._split(path.stem, text, version, task_id)
            self._save(passages)
            task.update(status="completed", doc_id=f"DOC-{task_id[:8].upper()}", chunks=len(passages))
        except Exception as exc:
            task.update(status="failed", error=str(exc))

    def _read_text(self, path: Path, task_id: str) -> str:
        """读取文本或使用本地 MinerU 解析 PDF。"""
        if path.suffix.lower() == ".pdf":
            from app.import_process.agent.nodes.node_pdf_to_md import node_pdf_to_md
            state = {"task_id": task_id, "pdf_path": str(path), "local_dir": str(path.parent)}
            return node_pdf_to_md(state)["md_content"]
        return path.read_text(encoding="utf-8-sig")

    def _split(self, title: str, text: str, version: str, task_id: str) -> list[Passage]:
        """按长度切分文本，保留文档与版本标识。"""
        text = text.strip()
        if not text:
            raise ValueError("文件没有可读取的文本内容")
        doc_id = f"DOC-{task_id[:8].upper()}"
        return [Passage(doc_id, version, f"{doc_id}-{index // 1000 + 1}", title, text[index:index + 1000])
                for index in range(0, len(text), 1000)]

    def _save(self, passages: list[Passage]) -> None:
        """生成向量并写入 Milvus，失败时抛出异常。"""
        from app.knowledge.milvus_writer import MilvusWriter
        with self.lock:
            MilvusWriter().insert(passages)
