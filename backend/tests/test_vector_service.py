"""
@Date: 2026-05-30
@Author: xisy
@Discription: Milvus 向量服务测试
"""

from typing import Any

import pytest

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.vector import MilvusVectorClient, MilvusVectorService, VectorRecord


class FakeSchema:
    """Milvus schema 伪对象。"""

    def __init__(self) -> None:
        self.fields: list[dict[str, Any]] = []

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
        self.schemas: dict[str, list[dict[str, Any]]] = {}

    def list_collections(self):
        return list(self.collections)

    def create_schema(self, **_kwargs):
        return FakeSchema()

    def prepare_index_params(self):
        return FakeIndexParams()

    def create_collection(self, collection_name, schema, **_kwargs):
        self.collections.append(collection_name)
        self.schemas[collection_name] = [self._build_describe_field(field) for field in schema.fields]

    def describe_collection(self, collection_name):
        return {"fields": self.schemas[collection_name]}

    def seed_collection(self, collection_name: str, fields: list[dict[str, Any]]) -> None:
        self.collections.append(collection_name)
        self.schemas[collection_name] = fields

    @staticmethod
    def _build_describe_field(field_definition: dict[str, Any]) -> dict[str, Any]:
        described_field = {
            "name": field_definition["field_name"],
            "type": field_definition["datatype"],
        }
        params: dict[str, Any] = {}
        if "max_length" in field_definition:
            params["max_length"] = field_definition["max_length"]
        if "dim" in field_definition:
            params["dim"] = field_definition["dim"]
        if params:
            described_field["params"] = params
        if field_definition.get("is_primary"):
            described_field["is_primary"] = True
        if field_definition.get("nullable"):
            described_field["nullable"] = True
        return described_field


class FakeMilvusServiceClient:
    """向量服务伪客户端。"""

    COLLECTION_SCHEMA_DEFINITIONS = MilvusVectorClient.COLLECTION_SCHEMA_DEFINITIONS

    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, Any]] = []

    def health_check(self):
        return {"status": "ok", "detail": "Milvus 连接正常"}

    def ensure_collections(self):
        return []

    def upsert(self, collection_name, data):
        self.upsert_calls.append({"collection_name": collection_name, "data": data})
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
                        "project_id": 99,
                        "knowledge_version_id": 88,
                        "chapter_node_id": 66,
                        "importance_level": 4,
                        "difficulty_level": 3,
                        "embedding_model": "text-embedding-3-large",
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
        vector_client.build_collection_name("semantic_chunk_vector"),
        vector_client.build_collection_name("knowledge_point_vector"),
    ]
    assert second_created == []


def test_ensure_collections_should_fail_when_existing_schema_drifted() -> None:
    """已有集合结构漂移时应显式报错。"""
    settings = get_settings()
    fake_client = FakeMilvusLowLevelClient()
    vector_client = MilvusVectorClient(settings)
    vector_client.get_client = lambda: fake_client

    fake_client.seed_collection(
        vector_client.build_collection_name("semantic_chunk_vector"),
        [
            {"name": "id", "type": "VARCHAR", "is_primary": True, "params": {"max_length": 128}},
            {"name": "project_id", "type": "INT64"},
            {"name": "content", "type": "VARCHAR", "params": {"max_length": 4096}},
            {"name": "embedding", "type": "FLOAT_VECTOR", "params": {"dim": settings.milvus_embedding_dim}},
        ],
    )

    with pytest.raises(AppException) as exc_info:
        vector_client.ensure_collections()

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert "schema 与当前设计不一致" in exc_info.value.message


def test_vector_service_upsert_delete_search_contract() -> None:
    """向量服务应提供稳定的写入、删除与检索契约。"""
    settings = get_settings()
    service = MilvusVectorService(client=FakeMilvusServiceClient(), settings=settings)
    records = [
        VectorRecord(
            id="kp-1",
            project_id=99,
            knowledge_version_id=88,
            chapter_node_id=66,
            importance_level=4,
            difficulty_level=3,
            embedding_model="text-embedding-3-large",
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
    assert search_result[0].collection_name == "knowledge_point_vector"
    assert search_result[0].knowledge_version_id == 88
    assert search_result[0].difficulty_level == 3


def test_vector_service_should_reject_content_over_utf8_max_length() -> None:
    """向量 content 超过 VARCHAR 字节上限时应拒绝写入。"""
    settings = get_settings()
    fake_client = FakeMilvusServiceClient()
    service = MilvusVectorService(client=fake_client, settings=settings)
    records = [
        VectorRecord(
            id="semantic_chunk:1",
            semantic_chunk_id=1,
            project_id=99,
            textbook_version_id=77,
            parse_version_id=66,
            knowledge_version_id=88,
            embedding_model="text-embedding-3-large",
            content="汉" * 3000,
            metadata={"chunk_no": 1},
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]

    with pytest.raises(AppException) as exc_info:
        service.upsert_vectors("semantic_chunk_vector", records)

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert "超过 Milvus VARCHAR 上限" in exc_info.value.message
    assert exc_info.value.details == {
        "collection_name": "semantic_chunk_vector",
        "field_name": "content",
        "max_utf8_bytes": 8192,
        "actual_utf8_bytes": 9000,
    }
    assert fake_client.upsert_calls == []


def test_vector_service_should_reject_metadata_over_json_max_length() -> None:
    """向量 metadata 超过 JSON 字段上限时应拒绝写入。"""
    settings = get_settings()
    fake_client = FakeMilvusServiceClient()
    service = MilvusVectorService(client=fake_client, settings=settings)
    records = [
        VectorRecord(
            id="semantic_chunk:2",
            semantic_chunk_id=2,
            project_id=99,
            textbook_version_id=77,
            parse_version_id=66,
            knowledge_version_id=88,
            embedding_model="text-embedding-3-large",
            content="正文",
            metadata={"source_block_refs_json": "引用" * 30000},
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]

    with pytest.raises(AppException) as exc_info:
        service.upsert_vectors("semantic_chunk_vector", records)

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert "超过 Milvus JSON 字段上限" in exc_info.value.message
    assert exc_info.value.details["collection_name"] == "semantic_chunk_vector"
    assert exc_info.value.details["field_name"] == "metadata"
    assert exc_info.value.details["max_utf8_bytes"] == 65536
    assert exc_info.value.details["actual_utf8_bytes"] > 65536
    assert fake_client.upsert_calls == []


def test_vector_service_should_reject_any_varchar_field_over_max_length() -> None:
    """任意 VARCHAR 字段超过 Milvus 上限时都应拒绝写入。"""
    settings = get_settings()
    fake_client = FakeMilvusServiceClient()
    service = MilvusVectorService(client=fake_client, settings=settings)
    records = [
        VectorRecord(
            id="semantic_chunk:3",
            semantic_chunk_id=3,
            project_id=99,
            textbook_version_id=77,
            parse_version_id=66,
            knowledge_version_id=88,
            embedding_model="model-" + "x" * 200,
            content="正文",
            metadata={"chunk_no": 3},
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]

    with pytest.raises(AppException) as exc_info:
        service.upsert_vectors("semantic_chunk_vector", records)

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert exc_info.value.details["field_name"] == "embedding_model"
    assert exc_info.value.details["max_utf8_bytes"] == 128
    assert exc_info.value.details["actual_utf8_bytes"] > 128
    assert fake_client.upsert_calls == []


def test_vector_service_dimension_mismatch_should_fail() -> None:
    """向量维度不匹配时应抛出业务异常。"""
    settings = get_settings()
    service = MilvusVectorService(client=FakeMilvusServiceClient(), settings=settings)
    records = [
        VectorRecord(
            id="kp-2",
            project_id=99,
            knowledge_version_id=88,
            embedding_model="text-embedding-3-large",
            embedding=[0.1, 0.2],
        )
    ]

    with pytest.raises(AppException):
        service.upsert_vectors("knowledge_point_vector", records)


def test_vector_service_should_require_collection_specific_fields() -> None:
    """服务层应校验集合特有过滤字段。"""
    settings = get_settings()
    service = MilvusVectorService(client=FakeMilvusServiceClient(), settings=settings)
    records = [
        VectorRecord(
            id="kp-3",
            project_id=99,
            embedding_model="text-embedding-3-large",
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]

    with pytest.raises(AppException) as exc_info:
        service.upsert_vectors("knowledge_point_vector", records)

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert exc_info.value.details == {
        "collection_name": "knowledge_point_vector",
        "missing_fields": ["knowledge_version_id"],
    }


def test_build_collection_name_should_return_logical_name_when_prefix_is_empty() -> None:
    """未配置前缀时应直接使用逻辑集合名。"""
    settings = Settings(
        mysql_host="127.0.0.1",
        mysql_username="root",
        mysql_password="boss1114",
        redis_uri="redis://127.0.0.1:6379/0",
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


def test_health_check_should_cache_import_error_and_return_controlled_detail(monkeypatch) -> None:
    """导入 pymilvus 失败时应返回受控错误，且避免重复导入。"""
    settings = get_settings()
    vector_client = MilvusVectorClient(settings)
    state = {"count": 0}

    def fake_import_milvus_client():
        state["count"] += 1
        raise ImportError("NumPy ABI 不兼容")

    monkeypatch.setattr(vector_client, "_import_milvus_client", fake_import_milvus_client)

    first_result = vector_client.health_check()
    second_result = vector_client.health_check()

    assert state["count"] == 1
    assert first_result == second_result
    assert first_result["status"] == "error"
    assert "Milvus 客户端初始化失败" in first_result["detail"]

    with pytest.raises(AppException) as exc_info:
        vector_client.get_client()

    assert exc_info.value.code == BusinessErrorCode.EXTERNAL_SERVICE_ERROR
    assert "NumPy" in exc_info.value.message
