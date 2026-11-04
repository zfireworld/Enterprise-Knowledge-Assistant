"""从 MinerU 内容列表构造有 PDF 页码的文本片段。"""

import json
from pathlib import Path
from typing import Any

from app.knowledge.chunking import split_text


def _block_text(block: dict[str, Any]) -> str:
    """保留内容块的文本、表格和图片引用；无内容时返回空串。"""
    parts: list[str] = []
    for key in ("text", "image_caption", "table_caption", "table_body", "image_footnote", "table_footnote"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    image_path = block.get("img_path")
    if block.get("type") == "image" and isinstance(image_path, str) and image_path:
        parts.append(f"![]({image_path})")
    return "\n".join(parts)


def split_pdf_pages(content_list: Path) -> list[tuple[int, str]]:
    """按 MinerU 物理页码切分完整文本；数据无效时抛出 ValueError。"""
    records = json.loads(content_list.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("MinerU 内容列表格式无效")
    pages: dict[int, list[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("MinerU 内容块格式无效")
        page = record.get("page_idx")
        text = _block_text(record)
        if not text:
            continue
        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            raise ValueError("MinerU 内容块缺少有效页码")
        pages.setdefault(page + 1, []).append(text)
    return [(page, chunk) for page, blocks in sorted(pages.items())
            for chunk in split_text("\n\n".join(blocks))]
