"""手动测试：调用本机 MinerU 将示例 PDF 转成 Markdown。"""

import json
from pathlib import Path

from app.import_process.agent.nodes.node_pdf_to_md import node_pdf_to_md
from app.import_process.agent.state import create_default_state


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    pdf_path = project_root / "doc" / "万用表RS-12的使用.pdf"
    output_dir = project_root / "output" / "manual_pdf_to_md"

    state = create_default_state(
        task_id="manual_pdf_to_md",
        is_pdf_read_enabled=True,
        local_dir=str(output_dir),
        local_file_path=str(pdf_path),
        pdf_path=str(pdf_path),
        file_title=pdf_path.stem,
    )
    result = node_pdf_to_md(state)
    print(json.dumps(result, ensure_ascii=False, indent=4))
