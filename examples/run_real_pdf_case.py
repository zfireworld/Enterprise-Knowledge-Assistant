"""使用合成 PDF 验证真实解析、向量检索和原文件页码定位。"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = uuid.uuid4().hex[:10]
COLLECTION = f"kb_pdf_eval_{RUN_ID}"
os.environ["CHUNKS_COLLECTION"] = COLLECTION
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("MODELSCOPE_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import fitz
from fastapi.testclient import TestClient
from app.knowledge.web_api import app
from app.knowledge.milvus_repository import MilvusRepository

OUTPUT = ROOT / "examples" / "live_runs" / RUN_ID


def sample_pdf() -> bytes:
    """生成包含两页合成制度的 PDF；返回文件字节。"""
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((72, 80), "Synthetic equipment safety guide", fontsize=16)
    first.insert_text((72, 120), "Follow the safety instructions before using the equipment.")
    second = doc.new_page()
    second.insert_text((72, 80), "Synthetic inspection rule", fontsize=16)
    second.insert_text((72, 120), "Inspect the equipment every 17 days.")
    content = doc.tobytes()
    doc.close()
    return content


def save(name: str, value: dict[str, Any]) -> None:
    """将实际输入和结果写到独立运行目录。"""
    (OUTPUT / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """运行 PDF 上传、真实解析、提问和原文件链接核验。"""
    OUTPUT.mkdir(parents=True, exist_ok=False)
    metadata = {"run_id": RUN_ID, "collection": COLLECTION, "model": os.getenv("LLM_DEFAULT_MODEL", ""),
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "input": "合成两页 PDF：第二页规定每 17 天检查设备"}
    save("metadata", metadata)
    pdf = sample_pdf()
    print(f"PDF_RUN_ID={RUN_ID} COLLECTION={COLLECTION}", flush=True)
    start = time.monotonic()
    try:
        with TestClient(app) as client:
            upload = client.post("/api/import", files={"file": ("inspection.pdf", pdf, "application/pdf")},
                                 data={"version_date": "2025-01-01"}, timeout=1900)
            upload.raise_for_status()
            task = client.get(f"/api/import/{upload.json()['id']}").json()
            save("pdf_import", task)
            print(f"PDF_IMPORT status={task['status']} elapsed={time.monotonic()-start:.1f}", flush=True)
            if task["status"] != "completed":
                raise RuntimeError(task.get("error", "PDF 导入未完成"))
            repo = MilvusRepository()
            records = repo.client.query(collection_name=COLLECTION, filter=f'doc_id == "{task["doc_id"]}"',
                                        limit=100, output_fields=["doc_id", "version_id", "page_number", "chunk_id", "content"])
            save("pdf_chunks", {"records": records})
            payload = {"question": "How often should the equipment be inspected?", "model": "real", "history": []}
            response = client.post("/api/chat", json=payload, timeout=300)
            result = response.json()
            save("pdf_question", {"input": payload, "http_status": response.status_code, "output": result})
            sources = [item for item in result.get("citations", []) if item.get("source_url")]
            source = sources[0] if sources else {}
            link = source.get("source_url", "")
            fetched = client.get(urlsplit(link).path) if link else None
            checks = {
                "page_1_and_2_indexed": {1, 2}.issubset({record.get("page_number") for record in records}),
                "answer_cites_page_2": result.get("status") == "completed" and any(
                    item.get("page_number") == 2 and "17 days" in item.get("quote", "").lower()
                    for item in result.get("citations", [])),
                "source_link_page_2": "#page=2" in link,
                "source_file_matches_upload": bool(fetched and fetched.status_code == 200 and fetched.content == pdf),
            }
            save("pdf_checks", {"checks": checks, "note": "浏览器 PDF 阅读器跳页未在本脚本中验证。"})
            print("PDF_CHECKS=" + json.dumps(checks), flush=True)
    except Exception as exc:
        save("pdf_error", {"type": type(exc).__name__, "message": str(exc), "elapsed_seconds": round(time.monotonic() - start, 2)})
        print(f"PDF_RUN_ERROR={type(exc).__name__}: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
