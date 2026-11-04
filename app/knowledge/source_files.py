"""解析文档版本保存的原文件并生成可访问的定位链接。"""

from pathlib import Path
from typing import Any
from urllib.parse import quote


def resolve_source(work_dir: Path, version: dict[str, Any]) -> Path:
    """解析已发布版本的文件，拒绝越界路径或不存在的文件。"""
    source = version.get("source") or {}
    storage_key = source.get("storage_key")
    if version.get("status") != "published" or not isinstance(storage_key, str) or not storage_key:
        raise FileNotFoundError("该版本没有可访问的原文件")
    root = work_dir.resolve()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("原文件不存在或路径无效")
    return path


def source_url(doc_id: str, version_id: str, page_number: int | None = None) -> str:
    """生成版本文件接口地址；有效页码添加浏览器 PDF 跳转片段。"""
    url = f"/api/documents/{quote(doc_id, safe='')}/versions/{quote(version_id, safe='')}/file"
    return f"{url}#page={page_number}" if page_number is not None else url


def version_source(store: Any, work_dir: Path, doc_id: str, version_id: str) -> Path:
    """按文档和版本读取已登记的原文件；不存在时抛出 FileNotFoundError。"""
    document = store.get(doc_id)
    if document is None:
        raise FileNotFoundError("文档不存在")
    version = next((item for item in document.get("versions", [])
                    if item.get("version_id") == version_id), None)
    if version is None:
        raise FileNotFoundError("文档版本不存在")
    return resolve_source(work_dir, version)
