"""验证真实 Milvus Hit 结构中的文档元数据不会丢失。"""

import unittest

from app.query_process.agent.nodes.node_rrf import _as_entity_list
from app.knowledge.milvus_repository import MilvusRepository


class DictHit(dict):
    """模拟同时拥有 dict 和 entity 接口的 pymilvus Hit。"""

    @property
    def entity(self) -> "DictHit":
        """模拟指向 Hit 自身的 entity 属性。"""
        return self

    @property
    def id(self) -> int:
        """返回测试主键。"""
        return 123

    @property
    def distance(self) -> float:
        """返回测试分数。"""
        return 0.9

    def to_dict(self) -> dict:
        """模拟返回外层 Hit 字典的 pymilvus 行为。"""
        return dict(self)


class MilvusResultNormalizationTests(unittest.TestCase):
    """确认搜索结果可供问答工具和引用校验使用。"""

    def test_dictionary_hit_extracts_nested_entity(self) -> None:
        """包含嵌套 entity 的 Hit 应保留文档 ID、版本及片段。"""
        hit = DictHit(chunk_id=123, distance=0.9, entity={
            "doc_id": "D01", "version_date": "2025-01-01", "chunk_id": 123,
            "content": "报销期限为30天。"})
        result = _as_entity_list([hit])
        self.assertEqual(result[0]["doc_id"], "D01")
        self.assertEqual(result[0]["version_date"], "2025-01-01")
        self.assertEqual(result[0]["content"], "报销期限为30天。")
        self.assertEqual(result[0]["chunk_id"], 123)

    def test_dictionary_hit_preserves_outer_primary_key(self) -> None:
        """片段主键只在外层时也能用于后续读取。"""
        hit = DictHit(chunk_id=123, distance=0.9, entity={"doc_id": "D01", "version_date": "2025-01-01"})
        self.assertEqual(_as_entity_list([hit])[0]["chunk_id"], 123)

    def test_search_filter_requires_metadata_fields(self) -> None:
        """旧切片缺少动态字段时，过滤表达式必须显式检查存在性。"""
        repository = object.__new__(MilvusRepository)
        repository._snapshot = {}
        expression = repository._version_filter()
        self.assertIn('(exists $meta["doc_id"])', expression)
        self.assertIn('(exists $meta["version_date"])', expression)


if __name__ == "__main__":
    unittest.main()
