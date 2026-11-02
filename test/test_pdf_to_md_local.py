import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.import_process.agent.nodes.node_pdf_to_md import node_pdf_to_md


class PdfToMarkdownTests(unittest.TestCase):
    def test_success_returns_generated_markdown_and_uses_local_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-test")
            md = root / "result" / "sample" / "auto" / "sample.md"
            md.parent.mkdir(parents=True)
            md.write_text("# 内容", encoding="utf-8")
            state = {"task_id": "test", "pdf_path": str(pdf), "local_dir": str(root / "result")}
            with patch("app.import_process.agent.nodes.node_pdf_to_md.subprocess.Popen") as popen, \
                 patch("app.import_process.agent.nodes.node_pdf_to_md.add_running_task"), \
                 patch("app.import_process.agent.nodes.node_pdf_to_md.add_done_task"):
                popen.return_value.stdout = io.StringIO("done\n")
                popen.return_value.wait.return_value = 0
                result = node_pdf_to_md(state)
                self.assertEqual(result["md_content"], "# 内容")
                self.assertEqual(Path(result["md_path"]), md.resolve())
                self.assertEqual(popen.call_args.kwargs["env"]["MINERU_MODEL_SOURCE"], "local")
                self.assertIn("pipeline", popen.call_args.args[0])

    def test_failed_process_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "sample.pdf"
            pdf.write_bytes(b"%PDF-test")
            state = {"task_id": "test", "pdf_path": str(pdf), "local_dir": temp}
            with patch("app.import_process.agent.nodes.node_pdf_to_md.subprocess.Popen") as popen, \
                 patch("app.import_process.agent.nodes.node_pdf_to_md.add_running_task"), \
                 patch("app.import_process.agent.nodes.node_pdf_to_md.add_done_task") as done, \
                 patch("app.import_process.agent.nodes.node_pdf_to_md.logger.exception"):
                popen.return_value.stdout = io.StringIO("failure\n")
                popen.return_value.wait.return_value = 1
                with self.assertRaisesRegex(RuntimeError, "退出码：1"):
                    node_pdf_to_md(state)
                done.assert_not_called()


if __name__ == "__main__":
    unittest.main()
