"""
@Date: 2026-05-29
@Author: xisy
@Discription: 原地迁移 semantic_chunk_vector 集合，新增 BM25 稀疏向量与中文分词以支持混合检索

迁移策略：先把现有行（含稠密 embedding 与 content 等标量字段）全量读出，删除集合后按新
schema（content 开启中文分词 + sparse + BM25 Function + 稀疏倒排索引）重建，再回灌原始数据；
sparse 由 Milvus 依据 content 自动生成，无需重新调用 Embedding 接口。
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.logging import configure_logging
from app.shared.vector import MilvusVectorClient

LOGICAL_NAME = "semantic_chunk_vector"
QUERY_BATCH_LIMIT = 16000
INSERT_BATCH_SIZE = 200


def _read_existing_rows(client, collection_name: str, output_fields: list[str]) -> list[dict]:
    """读取集合现有全部行（含稠密 embedding 与标量字段）。"""
    if collection_name not in set(client.list_collections()):
        print(f"集合不存在，无需迁移数据：{collection_name}")
        return []
    client.load_collection(collection_name=collection_name)
    rows = client.query(
        collection_name=collection_name,
        filter="semantic_chunk_id >= 0",
        output_fields=output_fields,
        limit=QUERY_BATCH_LIMIT,
    )
    print(f"已读取现有行：{len(rows)}")
    return list(rows)


def _reinsert_rows(client, collection_name: str, rows: list[dict]) -> int:
    """回灌历史行，剔除函数输出字段 sparse 后分批写入。"""
    inserted = 0
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = []
        for row in rows[start : start + INSERT_BATCH_SIZE]:
            payload = {key: value for key, value in row.items() if key != "sparse"}
            if not payload.get("embedding"):
                continue
            batch.append(payload)
        if not batch:
            continue
        client.insert(collection_name=collection_name, data=batch)
        inserted += len(batch)
    print(f"已回灌行：{inserted}")
    return inserted


def main() -> None:
    """执行 semantic_chunk_vector 集合的混合检索迁移。"""
    configure_logging()
    vector_client = MilvusVectorClient()
    client = vector_client.get_client()
    collection_name = vector_client.build_collection_name(LOGICAL_NAME)

    # 读取时需要稠密 embedding 才能无损迁移
    output_fields = vector_client.get_output_fields(LOGICAL_NAME) + ["embedding"]
    rows = _read_existing_rows(client, collection_name, output_fields)

    if collection_name in set(client.list_collections()):
        client.drop_collection(collection_name=collection_name)
        print(f"已删除集合：{collection_name}")

    vector_client._create_collection(LOGICAL_NAME)
    vector_client.validate_collection_schema(LOGICAL_NAME)
    print(f"已按新 schema 重建并校验集合：{collection_name}")

    if rows:
        _reinsert_rows(client, collection_name, rows)
        client.flush(collection_name=collection_name)

    stats = client.get_collection_stats(collection_name=collection_name)
    print(f"迁移完成，集合统计：{stats}")


if __name__ == "__main__":
    main()
