"""
@Date: 2026-04-30
@Author: xisy
@Discription: 重建 Milvus/Zilliz P0 必需集合脚本
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.logging import configure_logging
from app.shared.vector import MilvusVectorClient


def main() -> None:
    """按当前代码定义重建 P0 必需集合。"""
    configure_logging()

    vector_client = MilvusVectorClient()
    client = vector_client.get_client()
    existing_collections = set(client.list_collections())
    deprecated_collections = [
        vector_client.build_collection_name("textbook_chunk_vector"),
    ]
    recreated_collections: list[str] = []

    for collection_name in deprecated_collections:
        if collection_name in existing_collections:
            client.drop_collection(collection_name=collection_name)
            existing_collections.remove(collection_name)
            print(f"已删除废弃集合：{collection_name}")

    for logical_name in vector_client.REQUIRED_COLLECTIONS:
        collection_name = vector_client.build_collection_name(logical_name)
        if collection_name in existing_collections:
            client.drop_collection(collection_name=collection_name)
            print(f"已删除集合：{collection_name}")
        else:
            print(f"集合不存在，跳过删除：{collection_name}")

        vector_client._create_collection(logical_name)
        vector_client.validate_collection_schema(logical_name)
        recreated_collections.append(collection_name)
        print(f"已创建并校验集合：{collection_name}")

    print("Milvus/Zilliz P0 必需集合重建完成：")
    for collection_name in recreated_collections:
        print(f"- {collection_name}")


if __name__ == "__main__":
    main()
