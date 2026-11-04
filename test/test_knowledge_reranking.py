"""验证企业知识检索的重排序与旧版动态保留策略。"""

import unittest
from unittest.mock import patch

from app.knowledge.milvus_repository import MilvusRepository
from app.knowledge.reranking import rerank_candidates


class KnowledgeRerankingTests(unittest.TestCase):
    """使用可控分数核对排序、截断及元数据保留。"""

    def setUp(self) -> None:
        """准备具有不同文档与版本的候选片段。"""
        self.candidates = [
            {"doc_id": "D01", "chunk_id": 1, "version_id": "v1", "version_date": "2025-01-01",
             "content": "前文" * 100 + "真正的答案在末尾"},
            {"doc_id": "D02", "chunk_id": 2, "version_id": "v2", "version_date": "2025-02-01",
             "content": "相关的另一份规定"},
            {"doc_id": "D03", "chunk_id": 3, "version_id": "v3", "version_date": "2025-03-01",
             "content": "不相关的内容"},
        ]

    def test_full_text_is_scored_and_old_topk_policy_is_used(self) -> None:
        """使用完整原文评分，按旧断崖阈值截断并保留版本字段。"""
        with patch("app.lm.reranker_utils.rank_pairs", return_value=[0.94, 0.95, 0.1]) as rank:
            results = rerank_candidates("问题", self.candidates)
        self.assertEqual([item["doc_id"] for item in results], ["D02", "D01"])
        self.assertEqual([item["version_id"] for item in results], ["v2", "v1"])
        self.assertIn("真正的答案在末尾", rank.call_args.args[0][0][1])
        self.assertEqual(rank.call_args.args[0][0][0], "问题")

    def test_single_score_and_equal_scores(self) -> None:
        """单候选标量得分和无断崖的候选均正常保留。"""
        with patch("app.lm.reranker_utils.rank_pairs", return_value=0.3):
            self.assertEqual(len(rerank_candidates("问题", self.candidates[:1])), 1)
        with patch("app.lm.reranker_utils.rank_pairs", return_value=[0.4, 0.4, 0.4]):
            self.assertEqual(len(rerank_candidates("问题", self.candidates)), 3)

    def test_failure_and_invalid_scores_fall_back_to_rrf(self) -> None:
        """模型失败或分数异常时保留 RRF 候选顺序。"""
        with patch("app.lm.reranker_utils.rank_pairs", side_effect=RuntimeError("模型不可用")):
            self.assertEqual(rerank_candidates("问题", self.candidates), self.candidates)
        with patch("app.lm.reranker_utils.rank_pairs", return_value=[float("nan"), 1, 2]):
            self.assertEqual(rerank_candidates("问题", self.candidates), self.candidates)
        with patch("app.lm.reranker_utils.rank_pairs", return_value=[1, 2]):
            self.assertEqual(rerank_candidates("问题", self.candidates), self.candidates)

    def test_sync_search_uses_reranked_candidates(self) -> None:
        """同步双路召回后使用重排顺序且保留原始文档信息。"""
        repository = object.__new__(MilvusRepository)
        with patch.object(repository, "_search", side_effect=[self.candidates[:2], self.candidates[:2]]), \
             patch("app.query_process.agent.nodes.node_search_embedding_hyde.step_1_create_hyde_doc", return_value="假设"), \
             patch("app.knowledge.milvus_repository.rerank_candidates", side_effect=lambda query, items: list(reversed(items))) as rerank:
            results = repository.search("问题")
        self.assertEqual([item.doc_id for item in results], ["D02", "D01"])
        self.assertEqual([item.version_id for item in results], ["v2", "v1"])
        self.assertEqual(rerank.call_args.args[0], "问题")


class AsyncKnowledgeRerankingTests(unittest.IsolatedAsyncioTestCase):
    """验证网页使用的异步检索链路。"""

    async def test_async_search_uses_reranked_candidates(self) -> None:
        """异步双路召回同样在工作线程执行重排。"""
        repository = object.__new__(MilvusRepository)
        repository._snapshot = {}
        candidates = [{"doc_id": "D01", "chunk_id": 1, "version_date": "2025-01-01", "content": "内容一"},
                      {"doc_id": "D02", "chunk_id": 2, "version_date": "2025-01-01", "content": "内容二"}]
        with patch.object(repository, "_search", return_value=candidates), \
             patch("app.knowledge.milvus_repository._create_hyde", return_value="假设"), \
             patch("app.knowledge.milvus_repository.rerank_candidates", side_effect=lambda query, items: list(reversed(items))) as rerank:
            results = await repository.search_async("问题")
        self.assertEqual([item.doc_id for item in results], ["D02", "D01"])
        self.assertEqual(rerank.call_args.args[0], "问题")


if __name__ == "__main__":
    unittest.main()
