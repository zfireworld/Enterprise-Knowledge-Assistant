"""在独立 Milvus 集合中运行真实模型验收案例，并保存实际响应。"""

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = uuid.uuid4().hex[:10]
COLLECTION = f"kb_eval_{RUN_ID}"
os.environ["CHUNKS_COLLECTION"] = COLLECTION
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from fastapi.testclient import TestClient
from app.knowledge.web_api import app

OUTPUT = ROOT / "examples" / "live_runs" / RUN_ID
DATA = ROOT / "examples" / "manual_data"


def save(name: str, value: dict[str, Any]) -> None:
    """保存可审阅的输入、实际结果和运行记录。"""
    (OUTPUT / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def upload(client: TestClient, filename: str, date: str, doc_id: str = "") -> dict[str, Any]:
    """通过真实导入接口写入合成资料，返回完成后的任务状态。"""
    payload = {"version_date": date}
    if doc_id:
        payload["doc_id"] = doc_id
    response = client.post("/api/import", files={"file": (filename, (DATA / filename).read_bytes(), "text/markdown")}, data=payload)
    response.raise_for_status()
    task = client.get(f"/api/import/{response.json()['id']}")
    task.raise_for_status()
    result = task.json()
    if result["status"] != "completed":
        raise RuntimeError(f"导入失败：{result.get('error', result['status'])}")
    return result


def ask(client: TestClient, name: str, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """调用真实模型和向量检索，记录输入、HTTP 响应及运行时间。"""
    payload = {"question": question, "history": history or [], "model": "real"}
    start = time.monotonic()
    try:
        response = client.post("/api/chat", json=payload, timeout=300)
        result = {"http_status": response.status_code, "body": response.json()}
    except Exception as exc:
        result = {"http_status": None, "error": f"{type(exc).__name__}: {exc}"}
    record = {"mode": "real_model_real_milvus", "collection": COLLECTION, "input": payload,
              "elapsed_seconds": round(time.monotonic() - start, 2), "result": result}
    save(name, record)
    body = result.get("body", {})
    print(f"{name}: HTTP={result.get('http_status')}, status={body.get('status')}, seconds={record['elapsed_seconds']}", flush=True)
    return body


def contains_quote(result: dict[str, Any], doc_id: str, keyword: str) -> bool:
    """检查指定文档是否引用包含目标文字的片段。"""
    return any(item.get("doc_id") == doc_id and keyword in item.get("quote", "")
               for item in result.get("citations", []))


def verify_source(client: TestClient, result: dict[str, Any], expected: bytes) -> bool:
    """验证引用链接可访问对应的合成原文件。"""
    links = [item.get("source_url") for item in result.get("citations", []) if item.get("source_url")]
    if not links:
        return False
    response = client.get(urlsplit(links[0]).path)
    return response.status_code == 200 and response.content == expected


def main() -> None:
    """创建隔离集合并运行验收案例；异常保留已完成的记录。"""
    OUTPUT.mkdir(parents=True, exist_ok=False)
    meta = {"run_id": RUN_ID, "started_utc": datetime.now(timezone.utc).isoformat(), "collection": COLLECTION,
            "model": os.getenv("LLM_DEFAULT_MODEL", ""), "mode": "real_model_real_milvus",
            "tool_failure": "在单独案例中注入检索异常；其余案例无故障注入"}
    save("metadata", meta)
    print(f"RUN_ID={RUN_ID} COLLECTION={COLLECTION}", flush=True)
    try:
        with TestClient(app) as client:
            inputs = [("01-费用报销制度.md", "2025-01-01"), ("02-费用报销说明.md", "2025-02-01"),
                      ("03-账号登录FAQ.md", "2025-03-01"), ("04-年假制度.md", "2025-01-01")]
            docs = {filename: upload(client, filename, date) for filename, date in inputs}
            save("imports", {"collection": COLLECTION, "tasks": docs})
            print("Four synthetic documents imported", flush=True)
            cases = {"normal": "忘记登录密码怎么办？", "rewrite": "账号密码如何重置？",
                     "conflict": "报销期限多久？", "missing": "公司停车位收费吗？"}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {pool.submit(ask, client, name, question): name for name, question in cases.items()}
                results = {futures[future]: future.result() for future in as_completed(futures)}
            first = ask(client, "history_initial", "年假怎么规定？")
            history = [{"role": "user", "content": "年假怎么规定？"},
                       {"role": "assistant", "content": first.get("answer", "")}]
            results["history"] = ask(client, "history_followup", "有几天？", history)
            doc_id = docs["03-账号登录FAQ.md"]["doc_id"]
            updated = upload(client, "05-账号登录FAQ更新版.md", "2025-04-01", doc_id)
            save("updated_import", updated)
            results["updated"] = ask(client, "updated", "忘记登录密码怎么办？")
            from app.knowledge.milvus_repository import MilvusRepository
            with patch.object(MilvusRepository, "_search", side_effect=RuntimeError("验收测试：模拟 Milvus 检索失败")):
                results["tool_failure"] = ask(client, "tool_failure_injected", "报销期限多久？")
            assess(client, docs, updated, results)
    except Exception as exc:
        save("run_error", {"type": type(exc).__name__, "message": str(exc), "collection": COLLECTION})
        print(f"RUN_ERROR={type(exc).__name__}: {exc}", flush=True)
        raise


def assess(client: TestClient, docs: dict[str, dict[str, Any]], updated: dict[str, Any],
           results: dict[str, dict[str, Any]]) -> None:
    """对照合成资料输出初步检查，语义准确性仍须人工审核。"""
    account = docs["03-账号登录FAQ.md"]["doc_id"]
    d30 = docs["01-费用报销制度.md"]["doc_id"]
    d15 = docs["02-费用报销说明.md"]["doc_id"]
    leave = docs["04-年假制度.md"]["doc_id"]
    failure = results["tool_failure"]
    checks = {
        "normal": results["normal"].get("status") == "completed" and contains_quote(results["normal"], account, "内部账号平台"),
        "rewrite": results["rewrite"].get("status") == "completed" and contains_quote(results["rewrite"], account, "内部账号平台"),
        "conflict": results["conflict"].get("status") == "needs_clarification" and contains_quote(results["conflict"], d30, "30天") and contains_quote(results["conflict"], d15, "15天"),
        "missing": results["missing"].get("status") in {"insufficient", "needs_clarification"},
        "history": results["history"].get("status") == "completed" and contains_quote(results["history"], leave, "5天"),
        "updated": results["updated"].get("status") == "completed" and contains_quote(results["updated"], account, "服务台") and all(item.get("version_id") == updated["version_id"] for item in results["updated"].get("citations", [])),
        "tool_failure_injected": failure.get("status") == "incomplete" and any("模拟 Milvus 检索失败" in step.get("error", "") for step in failure.get("trace", [])),
        "source_file": verify_source(client, results["updated"], (DATA / "05-账号登录FAQ更新版.md").read_bytes()),
    }
    save("checks", {"checks": checks, "note": "初步自动检查，须结合完整 Trace 人工审核；工具失败为注入。"})
    print("CHECKS=" + json.dumps(checks, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
