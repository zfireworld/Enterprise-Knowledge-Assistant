"""为知识问答页面提供同源 API。"""

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.knowledge.import_service import ImportService
from app.knowledge.mock_model import MockDecisionModel
from app.knowledge.service import KnowledgeService
from app.knowledge.tools import KnowledgeTools

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "app" / "knowledge" / "web"
importer = ImportService(ROOT / "output" / "web_imports")
app = FastAPI(title="企业知识问答")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ChatRequest(BaseModel):
    """聊天请求及可选历史。"""

    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=30)
    model: Literal["real", "mock"] = "real"


@app.get("/")
def home() -> FileResponse:
    """返回统一工作台页面。"""
    return FileResponse(STATIC / "index.html")


@app.get("/api/documents")
def documents() -> list[dict]:
    """列出当前可查询的文档与片段数。"""
    from app.knowledge.milvus_repository import MilvusRepository
    try:
        return MilvusRepository().list_documents()
    except Exception as exc:
        raise HTTPException(503, f"知识库连接失败：{exc}") from exc


@app.post("/api/import", status_code=202)
async def import_document(background: BackgroundTasks, file: UploadFile = File(...),
                          version_date: date = Form(...)) -> dict:
    """接收 PDF、Markdown 或 UTF-8 文本，开始后台导入。"""
    name = file.filename or ""
    if Path(name).suffix.lower() not in {".pdf", ".md", ".txt"}:
        raise HTTPException(400, "请选择 PDF、Markdown 或 TXT 文件")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件为空或超过 10 MB")
    task = importer.create(name, content, version_date.isoformat())
    background.add_task(importer.process, task["id"], version_date.isoformat())
    return task


@app.get("/api/import/{task_id}")
def import_status(task_id: str) -> dict:
    """查询导入状态；不存在时返回 404。"""
    task = importer.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "导入任务不存在")
    return task.copy()


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    """使用共享知识库回答问题，返回引用和执行状态。"""
    if not request.question.strip():
        raise HTTPException(400, "请输入问题")
    if request.model == "real":
        from app.knowledge.model import LangChainDecisionModel
        try:
            model = LangChainDecisionModel()
        except Exception as exc:
            raise HTTPException(503, f"模型初始化失败：{exc}") from exc
    else:
        model = MockDecisionModel()
    from app.knowledge.milvus_repository import MilvusRepository
    try:
        repository = MilvusRepository()
    except Exception as exc:
        raise HTTPException(503, f"知识库连接失败：{exc}") from exc
    service = KnowledgeService(model, KnowledgeTools(repository))
    return service.ask(request.question, request.history)
