"""以 JSON 合成资料提供可重复运行的本地知识库。"""

import json
from pathlib import Path

from app.knowledge.domain import Passage


class LocalRepository:
    """从 path 加载资料；文件不存在或格式错误时抛出异常。"""

    def __init__(self, path: Path) -> None:
        """保存资料路径；每次读取文件以支持替换资料。"""
        self.path = path

    def list_passages(self) -> list[Passage]:
        """读取资料并返回片段列表；无效数据抛出异常。"""
        records = json.loads(self.path.read_text(encoding="utf-8"))
        return [Passage(**record) for record in records]

    def search(self, query: str) -> list[Passage]:
        """按主题词查找片段；未知主题返回空列表。"""
        groups = (("报销", "费用", "垫付"), ("假期", "放假", "年假", "休假", "请假"),
                  ("密码", "登录", "账号"))
        terms = next((group for group in groups if any(word in query for word in group)), ())
        return [item for item in self.list_passages() if terms and any(word in item.title + item.text for word in terms)]

    def read(self, doc_id: str, chunk_id: str) -> Passage:
        """按标识读取当前原文；未找到时抛出 LookupError。"""
        for item in self.list_passages():
            if (item.doc_id, item.chunk_id) == (doc_id, chunk_id):
                return item
        raise LookupError(f"片段不存在：{doc_id}/{chunk_id}")
