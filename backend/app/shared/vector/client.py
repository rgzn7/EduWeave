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
    # 各集合的 BM25 全文检索函数定义：input 文本字段 -> output 稀疏向量字段
    COLLECTION_FUNCTION_DEFINITIONS: dict[str, tuple[dict[str, Any], ...]] = {
        "semantic_chunk_vector": (
            {
                "name": "content_bm25",
                "function_type": "BM25",
                "input_field_names": ["content"],
                "output_field_names": ["sparse"],
            },
        ),
    }
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
            # content 开启中文分词器，作为 BM25 全文检索的输入字段
            {
                "field_name": "content",
                "datatype": "VARCHAR",
                "max_length": 8192,
                "nullable": True,
                "enable_analyzer": True,
                "analyzer_params": {"type": "chinese"},
            },
            {"field_name": "metadata", "datatype": "JSON", "nullable": True},
            {"field_name": "embedding", "datatype": "FLOAT_VECTOR", "dim_setting": "milvus_embedding_dim"},
            # sparse 由 BM25 Function 依据 content 自动生成，写入时无需提供
            {"field_name": "sparse", "datatype": "SPARSE_FLOAT_VECTOR"},
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

    def _get_index_params(self, client: Any, logical_name: str) -> Any:
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type=self.settings.milvus_index_type,
            metric_type=self.settings.milvus_metric_type,
            params={"M": 16, "efConstruction": 200},
        )
        # 若集合定义了 sparse 稀疏向量字段，则补充 BM25 稀疏倒排索引
        if any(
            field_definition["field_name"] == "sparse"
            for field_definition in self._get_collection_schema_definitions(logical_name)
        ):
            index_params.add_index(
                field_name="sparse",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="BM25",
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
        for key in ("is_primary", "max_length", "nullable", "enable_analyzer", "analyzer_params"):
            if key in field_definition:
                field_kwargs[key] = field_definition[key]
        if "dim_setting" in field_definition:
            field_kwargs["dim"] = getattr(self.settings, field_definition["dim_setting"])
        return field_kwargs

    def _apply_collection_functions(self, schema: Any, logical_name: str) -> None:
        """为集合 schema 追加 BM25 等内置函数。"""
        function_definitions = self.COLLECTION_FUNCTION_DEFINITIONS.get(logical_name)
        if not function_definitions:
            return
        from pymilvus import Function, FunctionType

        for function_definition in function_definitions:
            schema.add_function(
                Function(
                    name=function_definition["name"],
                    function_type=getattr(FunctionType, function_definition["function_type"]),
                    input_field_names=list(function_definition["input_field_names"]),
                    output_field_names=list(function_definition["output_field_names"]),
                )
            )

    def _create_collection(self, logical_name: str) -> None:
        client = self.get_client()
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        for field_definition in self._get_collection_schema_definitions(logical_name):
            schema.add_field(**self._build_field_kwargs(field_definition))
        self._apply_collection_functions(schema, logical_name)
        client.create_collection(
            collection_name=self.build_collection_name(logical_name),
            schema=schema,
            index_params=self._get_index_params(client, logical_name),
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
        """校验已有集合 schema 是否覆盖当前设计的字段。

        采用「期望字段为实际字段子集」的宽松比对：只要每个设计字段在实际集合中存在
        且类型一致即视为通过，忽略字段顺序、分词器/函数等附加元数据，避免误报漂移。
        """
        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        actual_schema = client.describe_collection(collection_name=collection_name)
        actual_type_by_name = {
            field_definition["name"]: self._normalize_datatype_name(field_definition["type"])
            for field_definition in actual_schema.get("fields", [])
        }
        expected_type_by_name = {
            field_definition["field_name"]: field_definition["datatype"]
            for field_definition in self._get_collection_schema_definitions(logical_name)
        }
        mismatched = {
            name: {"expected": expected_type, "actual": actual_type_by_name.get(name)}
            for name, expected_type in expected_type_by_name.items()
            if actual_type_by_name.get(name) != expected_type
        }
        if mismatched:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                f"Milvus 集合 {collection_name} 的 schema 与当前设计不一致，请清理后按新结构重建",
                details={"collection_name": collection_name, "mismatched_fields": mismatched},
            )

    _VECTOR_DATATYPES = frozenset({"FLOAT_VECTOR", "SPARSE_FLOAT_VECTOR", "BINARY_VECTOR"})

    def get_output_fields(self, logical_name: str) -> list[str]:
        """返回集合检索时应输出的字段（排除稠密/稀疏向量字段）。"""
        return [
            field_definition["field_name"]
            for field_definition in self._get_collection_schema_definitions(logical_name)
            if field_definition["datatype"] not in self._VECTOR_DATATYPES
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

    def hybrid_search(
        self,
        logical_name: str,
        *,
        query_vector: list[float],
        query_text: str,
        limit: int = 5,
        filter_expression: str | None = None,
        rrf_k: int = 60,
    ) -> list[list[dict[str, Any]]]:
        """执行稠密向量 + BM25 双路混合检索，经 RRF 重排融合结果。"""
        from pymilvus import AnnSearchRequest, RRFRanker

        client = self.get_client()
        collection_name = self.build_collection_name(logical_name)
        client.load_collection(collection_name=collection_name)
        dense_request = AnnSearchRequest(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": self.settings.milvus_metric_type, "params": {}},
            limit=limit,
            expr=filter_expression,
        )
        sparse_request = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse",
            param={"metric_type": "BM25", "params": {}},
            limit=limit,
            expr=filter_expression,
        )
        return client.hybrid_search(
            collection_name=collection_name,
            reqs=[dense_request, sparse_request],
            ranker=RRFRanker(rrf_k),
            limit=limit,
            output_fields=self.get_output_fields(logical_name),
        )
