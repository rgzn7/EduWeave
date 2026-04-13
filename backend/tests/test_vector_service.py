"""
@Date: 2026-04-11
@Author: xisy
@Discription: Milvus 向量服务测试
"""

import pytest

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.shared.vector import MilvusVectorClient, MilvusVectorService, VectorRecord


class FakeSchema:
    """Milvus schema 伪对象。"""

    def __init__(self) -> None:
        self.fields = []

    def add_field(self, **kwargs) -> None:
        self.fields.append(kwargs)


class FakeIndexParams:
    """Milvus 索引参数伪对象。"""

    def __init__(self) -> None:
        self.indexes = []

    def add_index(self, **kwargs) -> None:
        self.indexes.append(kwargs)


class FakeMilvusLowLevelClient:
    """MilvusClient 低层伪对象。"""

    def __init__(self) -> None:
        self.collections: list[str] = []

    def list_collections(self):
        return list(self.collections)

    def create_schema(self, **_kwargs):
        return FakeSchema()

    def prepare_index_params(self):
        return FakeIndexParams()

    def create_collection(self, collection_name, **_kwargs):
        self.collections.append(collection_name)


class FakeMilvusServiceClient:
    """向量服务伪客户端。"""

    def health_check(self):
        return {"status": "ok", "detail": "Milvus 连接正常"}

    def ensure_collections(self):
        return []

    def upsert(self, collection_name, data):
        return {"collection_name": collection_name, "upsert_count": len(data)}

    def delete(self, collection_name, ids):
        return {"collection_name": collection_name, "delete_count": len(ids)}

    def search(self, collection_name, vector, limit=5, filter_expression=None):
        _ = (collection_name, vector, limit, filter_expression)
        return [
            [
                {
                    "id": "kp-1",
                    "distance": 0.12,
                    "entity": {
                        "source_id": 1001,
                        "source_type": "knowledge_point",
                        "project_id": 99,
                        "content": "分数加减法",
                        "metadata": {"chapter": "第一单元"},
                    },
                }
            ]
        ]


def test_ensure_collections_should_be_idempotent() -> None:
    """ensure_collections 应支持幂等执行。"""
    settings = get_settings()
    fake_client = FakeMilvusLowLevelClient()
    vector_client = MilvusVectorClient(settings)
    vector_client.get_client = lambda: fake_client

    first_created = vector_client.ensure_collections()
    second_created = vector_client.ensure_collections()

    assert first_created == [
        f"{settings.milvus_collection_prefix}_textbook_chunk_vector",
        f"{settings.milvus_collection_prefix}_knowledge_point_vector",
    ]
    assert second_created == []


def test_vector_service_upsert_delete_search_contract() -> None:
    """向量服务应提供稳定的写入、删除与检索契约。"""
    settings = get_settings()
    service = MilvusVectorService(client=FakeMilvusServiceClient(), settings=settings)
    records = [
        VectorRecord(
            id="kp-1",
            source_id=1001,
            source_type="knowledge_point",
            project_id=99,
            content="分数加减法",
            metadata={"chapter": "第一单元"},
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]

    upsert_result = service.upsert_vectors("knowledge_point_vector", records)
    delete_result = service.delete_vectors("knowledge_point_vector", ["kp-1"])
    search_result = service.search_vectors("knowledge_point_vector", [0.1, 0.2, 0.3, 0.4], limit=3)

    assert upsert_result == {"upsert_count": 1}
    assert delete_result == {"delete_count": 1}
    assert len(search_result) == 1
    assert search_result[0].id == "kp-1"
    assert search_result[0].source_type == "knowledge_point"


def test_vector_service_dimension_mismatch_should_fail() -> None:
    """向量维度不匹配时应抛出业务异常。"""
    settings = get_settings()
    service = MilvusVectorService(client=FakeMilvusServiceClient(), settings=settings)
    records = [
        VectorRecord(
            id="kp-2",
            source_id=1002,
            source_type="knowledge_point",
            embedding=[0.1, 0.2],
        )
    ]

    with pytest.raises(AppException):
        service.upsert_vectors("knowledge_point_vector", records)


def test_build_collection_name_should_return_logical_name_when_prefix_is_empty() -> None:
    """未配置前缀时应直接使用逻辑集合名。"""
    settings = Settings(
        mysql_host="127.0.0.1",
        mysql_user="root",
        mysql_password="boss1114",
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret="test-secret",
        obs_endpoint="https://obs.test.example.com",
        obs_ak="test-ak",
        obs_sk="test-sk",
        obs_bucket="test-bucket",
        milvus_uri="http://127.0.0.1:19530",
        milvus_collection_prefix="   ",
        milvus_embedding_dim=4,
    )
    vector_client = MilvusVectorClient(settings)

    assert vector_client.build_collection_name("knowledge_point_vector") == "knowledge_point_vector"
