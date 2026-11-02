"""将合成资料导入全新 Milvus 集合。"""

import argparse
from pathlib import Path
from typing import Any

from app.knowledge.local_repository import LocalRepository


def _records(data_path: Path) -> tuple[list[dict[str, Any]], int]:
    """读取 data_path 并生成 BGE 向量；返回记录及向量维度。"""
    from app.lm.embedding_utils import generate_embeddings
    passages = LocalRepository(data_path).list_passages()
    if not passages:
        raise ValueError("资料为空")
    vectors = generate_embeddings([f"{item.title}\n{item.text}" for item in passages])
    records = []
    for index, item in enumerate(passages):
        records.append({"doc_id": item.doc_id, "version_date": item.version_date,
                        "title": item.title, "parent_title": item.title, "part": 0,
                        "file_title": item.title, "item_name": "", "content": item.text,
                        "dense_vector": vectors["dense"][index], "sparse_vector": vectors["sparse"][index]})
    return records, len(records[0]["dense_vector"])


def main() -> None:
    """创建指定的新集合并写入资料；集合已存在或依赖失败时抛出异常。"""
    from app.clients.milvus_utils import get_milvus_client
    from app.import_process.agent.nodes.node_import_milvus import create_collection
    parser = argparse.ArgumentParser(description="将合成资料写入新的 Milvus 集合")
    parser.add_argument("collection", help="新集合名称，需与 CHUNKS_COLLECTION 一致")
    parser.add_argument("--data", type=Path, default=Path("data/knowledge.json"))
    args = parser.parse_args()
    client = get_milvus_client()
    if client is None:
        raise RuntimeError("无法连接 Milvus")
    if client.has_collection(args.collection):
        raise ValueError("集合已存在；请指定新的集合，避免覆盖已有数据")
    records, dimension = _records(args.data)
    create_collection(client, args.collection, dimension)
    result = client.insert(collection_name=args.collection, data=records)
    print(f"已写入 {len(result['ids'])} 个片段，集合：{args.collection}")


if __name__ == "__main__":
    main()
