"""
@Date: 2026-04-11
@Author: xisy
@Discription: Milvus 底层客户端封装
"""

from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode


class MilvusVectorClient:
    """Milvus 统一客户端。"""

    REQUIRED_COLLECTIONS = (
        "textbook_chunk_vector",
        "knowledge_point_vector",
    )
    RESERVED_COLLECTIONS = (
        "question_sample_vector",
        "template_fragment_vector",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any | None = None

    def get_client(self) -> Any:
        """懒加载 MilvusClient。"""
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(
                uri=self.settings.milvus_uri,
                token=self.settings.milvus_token,
                db_name=self.settings.milvus_db_name,
            )
        return self._client

    def build_collection_name(self, logical_name: str) -> str:
        """拼接实际集合名称。"""
        prefix = self.settings.milvus_collection_prefix
        if not prefix:
            return logical_name
        return f"{prefix}_{logical_name}"

    def _get_index_params(self, client: Any) -> Any:
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type=self.settings.milvus_index_type,
            metric_type=self.settings.milvus_metric_type,
            params={"M": 16, "efConstruction": 200},
        )
        return index_params

    def _create_collection(self, logical_name: str) -> None:
        from pymilvus import DataType

        client = self.get_client()
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(field_name="source_id", datatype=DataType.INT64)
        schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="project_id", datatype=DataType.INT64)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=4096)
        schema.add_field(field_name="metadata", datatype=DataType.JSON)
        schema.add_field(
            field_name="embedding",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.settings.milvus_embedding_dim,
        )
        client.create_collection(
            collection_name=self.build_collection_name(logical_name),
            schema=schema,
            index_params=self._get_index_params(client),
        )

    def health_check(self) -> dict[str, str]:
        """执行 Milvus 健康检查。"""
        try:
            client = self.get_client()
            client.list_collections()
            return {"status": "ok", "detail": "Milvus 连接正常"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": f"Milvus 检查失败：{exc}"}

    def ensure_collections(self) -> list[str]:
        """确保 P0 必需集合存在，且方法可重复执行。"""
        client = self.get_client()
        existing = set(client.list_collections())
        created_collections: list[str] = []
        for logical_name in self.REQUIRED_COLLECTIONS:
            collection_name = self.build_collection_name(logical_name)
            if collection_name in existing:
                continue
            self._create_collection(logical_name)
            created_collections.append(collection_name)
        return created_collections

    def upsert(self, logical_name: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        """执行向量写入或更新。"""
        if not data:
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "待写入向量数据不能为空")
        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        return client.upsert(collection_name=collection_name, data=data)

    def delete(self, logical_name: str, ids: list[str]) -> dict[str, Any]:
        """按主键删除向量。"""
        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        return client.delete(collection_name=collection_name, ids=ids)

    def search(
        self,
        logical_name: str,
        vector: list[float],
        limit: int = 5,
        filter_expression: str | None = None,
    ) -> list[list[dict[str, Any]]]:
        """执行向量检索。"""
        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        client.load_collection(collection_name=collection_name)
        return client.search(
            collection_name=collection_name,
            data=[vector],
            limit=limit,
            filter=filter_expression,
            output_fields=["source_id", "source_type", "project_id", "content", "metadata"],
        )
