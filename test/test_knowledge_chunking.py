"""验证导入文档的切分边界和元数据。"""

import tempfile
import unittest
from pathlib import Path

from app.knowledge.chunking import CHUNK_OVERLAP, CHUNK_SIZE, split_text
from app.knowledge.import_service import ImportService


class KnowledgeChunkingTests(unittest.TestCase):
    """验证切分长度、重叠和原文保留。"""

    def test_long_unbroken_text_overlaps_at_boundary(self) -> None:
        """连续长文本的相邻片段应共享边界上下文。"""
        text = "".join(chr(0x4e00 + index) for index in range(1400))
        chunks = split_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= CHUNK_SIZE for chunk in chunks))
        self.assertEqual(chunks[0][-CHUNK_OVERLAP:], chunks[1][:CHUNK_OVERLAP])
        self.assertEqual(chunks[0] + chunks[1][CHUNK_OVERLAP:], text)

    def test_sentence_boundaries_keep_original_text(self) -> None:
        """长度允许时，句子应保持完整且内容来自原文。"""
        sentences = ["甲" * 350 + "。", "乙" * 350 + "。", "丙" * 350 + "。"]
        text = "".join(sentences)
        chunks = split_text(text)
        self.assertTrue(all(any(sentence in chunk for chunk in chunks) for sentence in sentences))
        self.assertTrue(all(chunk in text and len(chunk) <= CHUNK_SIZE for chunk in chunks))

    def test_import_keeps_document_metadata(self) -> None:
        """导入后每个片段保留同一文档 ID 和版本日期。"""
        with tempfile.TemporaryDirectory() as directory:
            service = ImportService(Path(directory))
            text = "测试内容" * 300
            chunks = service._split("制度", text, "2026-01-01", "1234567890")
            self.assertGreater(len(chunks), 1)
            self.assertEqual({chunk.doc_id for chunk in chunks}, {"DOC-12345678"})
            self.assertEqual({chunk.version_date for chunk in chunks}, {"2026-01-01"})
            self.assertEqual(len({chunk.chunk_id for chunk in chunks}), len(chunks))
            self.assertTrue(all(chunk.text in text for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
