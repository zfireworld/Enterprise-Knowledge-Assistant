"""通过本机 MinerU 命令将 PDF 转换为 Markdown。"""

import os
import subprocess
import time
from pathlib import Path

from app.core.logger import logger
from app.import_process.agent.state import ImportGraphState
from app.utils.task_utils import add_done_task, add_running_task


def step_1_validate_paths(state: ImportGraphState) -> tuple[Path, Path]:
    pdf_path = state.get("pdf_path", "")
    local_dir = state.get("local_dir", "")
    if not pdf_path or not local_dir:
        raise ValueError("PDF 转换需要 pdf_path 和 local_dir")

    pdf = Path(pdf_path).resolve()
    output_dir = Path(local_dir).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 文件不存在：{pdf}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return pdf, output_dir


def convert_pdf_locally(pdf: Path, output_dir: Path) -> Path:
    """运行 MinerU pipeline，返回其生成的 Markdown 文件路径。"""
    executable = os.environ.get("MINERU_EXECUTABLE", "mineru")
    command = [executable, "-p", str(pdf), "-o", str(output_dir), "-b", "pipeline"]
    env = os.environ.copy()
    env["MINERU_MODEL_SOURCE"] = "local"
    env["PYTHONUTF8"] = "1"
    start = time.monotonic()
    logger.info(f"开始本地 MinerU 解析：{pdf}")
    log_path = output_dir / f"{pdf.stem}.mineru.log"
    # MinerU 子进程可能继承 stdout；等待管道 EOF 会被遗留进程无限阻塞。
    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT, env=env)
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 mineru 命令；请安装本地 MinerU 或设置 MINERU_EXECUTABLE。") from exc
        try:
            return_code = process.wait(timeout=1800)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise TimeoutError(f"MinerU 解析超时，日志：{log_path}") from exc
    if return_code != 0:
        raise RuntimeError(f"本地 MinerU 解析失败，退出码：{return_code}，日志：{log_path}")

    md_path = output_dir / pdf.stem / "auto" / f"{pdf.stem}.md"
    if not md_path.is_file():
        raise FileNotFoundError(f"MinerU 执行成功，但未找到预期的 Markdown 文件：{md_path}")
    logger.info(f"本地 MinerU 解析完成，耗时 {time.monotonic() - start:.2f} 秒：{md_path}")
    return md_path


def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """解析 PDF 并更新下游图片处理节点所需的路径和文本。"""
    node_name = "node_pdf_to_md"
    add_running_task(state["task_id"], node_name)
    try:
        pdf, output_dir = step_1_validate_paths(state)
        md_path = convert_pdf_locally(pdf, output_dir)
        content = md_path.read_text(encoding="utf-8")
        state["md_path"] = str(md_path)
        state["md_content"] = content
        add_done_task(state["task_id"], node_name)
        return state
    except Exception:
        logger.exception("本地 PDF 转 Markdown 失败")
        raise
