"""将上传文件转换为知识片段并保存到本地仓库。"""

import threading
import uuid
import os
from pathlib import Path
from typing import TYPE_CHECKING

from app.knowledge.chunking import split_text
from app.knowledge.domain import Passage

if TYPE_CHECKING:
    from app.knowledge.version_repository import VersionRepository


class ImportService:
    """管理单进程内的文件导入和任务状态。"""

    def __init__(self, work_dir: Path) -> None:
        """初始化工作目录和导入任务状态。"""
        self.work_dir = work_dir
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()

    def create(self, filename: str, content: bytes, version: str, doc_id: str | None = None) -> dict:
        """创建任务并暂存文件；返回可供轮询的任务信息。"""
        task_id = uuid.uuid4().hex
        name = Path(filename.replace("\\", "/")).name
        folder = self.work_dir / task_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        store, target, title = self._prepare_document(doc_id, task_id, name)
        revision = store.reserve(target, title, version, new_document=doc_id is None)
        self.tasks[task_id] = {"id": task_id, "filename": name, "status": "pending", "doc_id": target,
                               "title": title, "version_id": revision["version_id"], "version_number": revision["number"],
                               "version": revision}
        return self.tasks[task_id].copy()

    def _store(self) -> "VersionRepository":
        """根据当前 Milvus 集合获取版本仓库。"""
        from app.knowledge.version_repository import VersionRepository
        collection = os.getenv("CHUNKS_COLLECTION")
        if not collection:
            raise RuntimeError("未配置 CHUNKS_COLLECTION")
        return VersionRepository(collection)

    def _prepare_document(self, doc_id: str | None, task_id: str, name: str) -> tuple["VersionRepository", str, str]:
        """获取版本仓库并验证目标；旧文档在更新时登记为 V1。"""
        store = self._store()
        if doc_id is None:
            return store, f"DOC-{task_id[:8].upper()}", Path(name).stem
        document = store.get(doc_id)
        if document is None:
            from app.knowledge.milvus_repository import MilvusRepository
            repository = MilvusRepository()
            legacy = next((item for item in repository.list_legacy_documents() if item["doc_id"] == doc_id), None)
            if legacy is None:
                raise LookupError("要更新的文档不存在")
            store.register_legacy(legacy)
            document = store.get(doc_id)
        return store, doc_id, document["title"]

    def process(self, task_id: str, version: str) -> None:
        """解析任务文件并保存片段；失败时记录明确错误。"""
        task = self.tasks[task_id]
        task.update(status="processing", step="正在解析文档")
        try:
            path = self.work_dir / task_id / task["filename"]
            text = self._read_text(path, task_id)
            passages = self._split(task["title"], text, version, task_id, task["doc_id"], task["version_id"])
            task.update(step="正在生成向量并写入知识库", chunks=len(passages))
            self._save(passages)
            self._store().publish(task["doc_id"], task["version"], len(passages))
            task.update(status="completed", chunks=len(passages), step="版本已发布")
        except Exception as exc:
            task.update(status="failed", error=str(exc))
            try:
                self._store().fail(task["doc_id"], task["version_id"], str(exc))
            except Exception as metadata_error:
                task["error"] += f"；版本状态更新失败：{metadata_error}"

    def _read_text(self, path: Path, task_id: str) -> str:
        """读取文本或使用本地 MinerU 解析 PDF。"""
        if path.suffix.lower() == ".pdf":
            from app.import_process.agent.nodes.node_pdf_to_md import node_pdf_to_md
            state = {"task_id": task_id, "pdf_path": str(path), "local_dir": str(path.parent)}
            return node_pdf_to_md(state)["md_content"]
        return path.read_text(encoding="utf-8-sig")

    def _split(self, title: str, text: str, version: str, task_id: str,
               doc_id: str | None = None, version_id: str = "") -> list[Passage]:
        """按段落和句子切分文本，保留重叠及文档版本标识。"""
        text = text.strip()
        if not text:
            raise ValueError("文件没有可读取的文本内容")
        doc_id = doc_id or f"DOC-{task_id[:8].upper()}"
        return [Passage(doc_id, version, f"{doc_id}-{index}", title, chunk, version_id)
                for index, chunk in enumerate(split_text(text), start=1)]

    def _save(self, passages: list[Passage]) -> None:
        """生成向量并写入 Milvus，失败时抛出异常。"""
        from app.knowledge.milvus_writer import MilvusWriter
        with self.lock:
            MilvusWriter().insert(passages)
