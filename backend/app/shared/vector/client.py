"""
@Date: 2026-04-30
@Author: xisy
@Discription: Milvus 底层客户端封装
"""

from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode


class MilvusVectorClient:
    """Milvus 统一客户端。"""

    REQUIRED_COLLECTIONS = (
        "semantic_chunk_vector",
        "knowledge_point_vector",
    )
    RESERVED_COLLECTIONS = (
        "question_sample_vector",
        "template_fragment_vector",
    )
    COLLECTION_SCHEMA_DEFINITIONS: dict[str, tuple[dict[str, Any], ...]] = {
        "semantic_chunk_vector": (
            {"field_name": "id", "datatype": "VARCHAR", "is_primary": True, "max_length": 128},
            {"field_name": "semantic_chunk_id", "datatype": "INT64"},
            {"field_name": "project_id", "datatype": "INT64"},
            {"field_name": "textbook_version_id", "datatype": "INT64"},
            {"field_name": "parse_version_id", "datatype": "INT64"},
            {"field_name": "knowledge_version_id", "datatype": "INT64"},
            {"field_name": "chapter_node_id", "datatype": "INT64", "nullable": True},
            {"field_name": "page_start", "datatype": "INT64", "nullable": True},
            {"field_name": "page_end", "datatype": "INT64", "nullable": True},
            {"field_name": "chunk_type", "datatype": "VARCHAR", "max_length": 32, "nullable": True},
            {"field_name": "embedding_model", "datatype": "VARCHAR", "max_length": 128},
            {"field_name": "content", "datatype": "VARCHAR", "max_length": 8192, "nullable": True},
            {"field_name": "metadata", "datatype": "JSON", "nullable": True},
            {"field_name": "embedding", "datatype": "FLOAT_VECTOR", "dim_setting": "milvus_embedding_dim"},
        ),
        "knowledge_point_vector": (
            {"field_name": "id", "datatype": "VARCHAR", "is_primary": True, "max_length": 128},
            {"field_name": "project_id", "datatype": "INT64"},
            {"field_name": "knowledge_version_id", "datatype": "INT64"},
            {"field_name": "chapter_node_id", "datatype": "INT64", "nullable": True},
            {"field_name": "importance_level", "datatype": "INT64", "nullable": True},
            {"field_name": "difficulty_level", "datatype": "INT64", "nullable": True},
            {"field_name": "embedding_model", "datatype": "VARCHAR", "max_length": 128},
            {"field_name": "content", "datatype": "VARCHAR", "max_length": 8192, "nullable": True},
            {"field_name": "metadata", "datatype": "JSON", "nullable": True},
            {"field_name": "embedding", "datatype": "FLOAT_VECTOR", "dim_setting": "milvus_embedding_dim"},
        ),
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any | None = None
        self._client_import_error: AppException | None = None

    def _import_milvus_client(self) -> Any:
        """导入 pymilvus 客户端类型。"""
        from pymilvus import MilvusClient

        return MilvusClient

    def _build_client_import_exception(self, exc: Exception) -> AppException:
        """构造 Milvus 客户端导入失败的统一业务异常。"""
        return AppException(
            BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
            "Milvus 客户端初始化失败，请检查 pymilvus 依赖是否完整，并确认 NumPy 与相关二进制扩展版本兼容",
            details={"error": str(exc)},
        )

    def get_client(self) -> Any:
        """懒加载 MilvusClient。"""
        if self._client_import_error is not None:
            raise self._client_import_error
        if self._client is None:
            try:
                MilvusClient = self._import_milvus_client()
            except Exception as exc:  # noqa: BLE001
                self._client_import_error = self._build_client_import_exception(exc)
                raise self._client_import_error from exc

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

    def _get_collection_schema_definitions(self, logical_name: str) -> tuple[dict[str, Any], ...]:
        """返回指定集合的 schema 定义。"""
        if logical_name not in self.COLLECTION_SCHEMA_DEFINITIONS:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                f"Milvus 集合 {logical_name} 暂未定义 schema，请先完成集合设计后再接入",
            )
        return self.COLLECTION_SCHEMA_DEFINITIONS[logical_name]

    def _build_field_kwargs(self, field_definition: dict[str, Any]) -> dict[str, Any]:
        """将字段定义转换为 pymilvus 所需参数。"""
        from pymilvus import DataType

        field_kwargs: dict[str, Any] = {
            "field_name": field_definition["field_name"],
            "datatype": getattr(DataType, field_definition["datatype"]),
        }
        for key in ("is_primary", "max_length", "nullable"):
            if key in field_definition:
                field_kwargs[key] = field_definition[key]
        if "dim_setting" in field_definition:
            field_kwargs["dim"] = getattr(self.settings, field_definition["dim_setting"])
        return field_kwargs

    def _create_collection(self, logical_name: str) -> None:
        client = self.get_client()
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        for field_definition in self._get_collection_schema_definitions(logical_name):
            schema.add_field(**self._build_field_kwargs(field_definition))
        client.create_collection(
            collection_name=self.build_collection_name(logical_name),
            schema=schema,
            index_params=self._get_index_params(client),
        )

    def _normalize_datatype_name(self, datatype: Any) -> str:
        """将 pymilvus 的字段类型归一为稳定字符串。"""
        from pymilvus import DataType

        try:
            return DataType(datatype).name
        except Exception:  # noqa: BLE001
            return getattr(datatype, "name", str(datatype).split(".")[-1])

    def _normalize_field_signature(self, field_definition: dict[str, Any]) -> dict[str, Any]:
        """归一化字段签名，便于做 schema 漂移比对。"""
        params: dict[str, int] = {}
        if "max_length" in field_definition:
            params["max_length"] = int(field_definition["max_length"])
        if "dim_setting" in field_definition:
            params["dim"] = int(getattr(self.settings, field_definition["dim_setting"]))

        normalized_field = {
            "name": field_definition["field_name"],
            "type": field_definition["datatype"],
            "is_primary": bool(field_definition.get("is_primary", False)),
            "nullable": bool(field_definition.get("nullable", False)),
        }
        if params:
            normalized_field["params"] = params
        return normalized_field

    def _normalize_actual_field_signature(self, field_definition: dict[str, Any]) -> dict[str, Any]:
        """归一化现有 Milvus 字段描述。"""
        raw_params = field_definition.get("params") or {}
        params: dict[str, int] = {}
        if "max_length" in raw_params:
            params["max_length"] = int(raw_params["max_length"])
        if "dim" in raw_params:
            params["dim"] = int(raw_params["dim"])

        normalized_field = {
            "name": field_definition["name"],
            "type": self._normalize_datatype_name(field_definition["type"]),
            "is_primary": bool(field_definition.get("is_primary", False)),
            "nullable": bool(field_definition.get("nullable", False)),
        }
        if params:
            normalized_field["params"] = params
        return normalized_field

    def validate_collection_schema(self, logical_name: str) -> None:
        """校验已有集合 schema 是否与当前设计一致。"""
        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        actual_schema = client.describe_collection(collection_name=collection_name)
        actual_fields = [
            self._normalize_actual_field_signature(field_definition)
            for field_definition in actual_schema.get("fields", [])
        ]
        expected_fields = [
            self._normalize_field_signature(field_definition)
            for field_definition in self._get_collection_schema_definitions(logical_name)
        ]

        if actual_fields != expected_fields:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                f"Milvus 集合 {collection_name} 的 schema 与当前设计不一致，请清理后按新结构重建",
                details={
                    "collection_name": collection_name,
                    "expected_fields": expected_fields,
                    "actual_fields": actual_fields,
                },
            )

    def get_output_fields(self, logical_name: str) -> list[str]:
        """返回集合检索时应输出的字段。"""
        return [
            field_definition["field_name"]
            for field_definition in self._get_collection_schema_definitions(logical_name)
            if field_definition["field_name"] != "embedding"
        ]

    def health_check(self) -> dict[str, str]:
        """执行 Milvus 健康检查。"""
        try:
            client = self.get_client()
            client.list_collections()
            return {"status": "ok", "detail": "Milvus 连接正常"}
        except AppException as exc:
            return {"status": "error", "detail": exc.message}
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
                self.validate_collection_schema(logical_name)
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
            output_fields=self.get_output_fields(logical_name),
        )
