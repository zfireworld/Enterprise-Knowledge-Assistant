@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Project environment not found. Run: uv sync
    exit /b 1
)
if not exist ".env" echo Note: .env was not found; environment variables must be configured separately.

echo Starting knowledge workspace at http://127.0.0.1:8090/
echo Start MongoDB, Milvus, and your model service separately.
echo Press Ctrl+C to stop the workspace.
".venv\Scripts\python.exe" -m uvicorn app.knowledge.web_api:app --host 127.0.0.1 --port 8090
exit /b %errorlevel%
