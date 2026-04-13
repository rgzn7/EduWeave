"""
@Date: 2026-04-13
@Author: xisy
@Discription: Milvus 向量服务封装
"""

from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.vector.client import MilvusVectorClient
from app.shared.vector.schemas import VectorRecord, VectorSearchHit


class MilvusVectorService:
    """屏蔽 pymilvus 细节的向量服务层。"""

    REQUIRED_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
        "textbook_chunk_vector": ("textbook_version_id", "parse_version_id"),
        "knowledge_point_vector": ("knowledge_version_id",),
    }

    def __init__(self, client: MilvusVectorClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or MilvusVectorClient(self.settings)

    def health_check(self) -> dict[str, str]:
        """执行 Milvus 健康检查。"""
        return self.client.health_check()

    def ensure_collections(self) -> list[str]:
        """引导初始化所有必需集合。"""
        return self.client.ensure_collections()

    def _ensure_supported_collection(self, collection_name: str) -> None:
        """校验当前集合是否已经完成 schema 设计。"""
        if collection_name not in self.client.COLLECTION_SCHEMA_DEFINITIONS:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                f"Milvus 集合 {collection_name} 暂未定义可用 schema，暂不支持写入或检索",
            )

    def _ensure_required_fields(self, collection_name: str, record: VectorRecord) -> None:
        """按集合校验写入记录必填字段。"""
        required_fields = self.REQUIRED_RECORD_FIELDS.get(collection_name, ())
        missing_fields = [field_name for field_name in required_fields if getattr(record, field_name) is None]
        if missing_fields:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                "向量记录缺少集合所需过滤字段",
                details={"collection_name": collection_name, "missing_fields": missing_fields},
            )

    def _normalize_record(self, collection_name: str, record: VectorRecord) -> dict[str, Any]:
        """按集合结构归一化写入记录。"""
        self._ensure_required_fields(collection_name, record)
        if collection_name == "textbook_chunk_vector":
            return {
                "id": record.id,
                "project_id": record.project_id,
                "textbook_version_id": record.textbook_version_id,
                "parse_version_id": record.parse_version_id,
                "chapter_node_id": record.chapter_node_id,
                "page_no": record.page_no,
                "block_type": record.block_type,
                "embedding_model": record.embedding_model,
                "content": record.content,
                "metadata": record.metadata,
                "embedding": record.embedding,
            }
        if collection_name == "knowledge_point_vector":
            return {
                "id": record.id,
                "project_id": record.project_id,
                "knowledge_version_id": record.knowledge_version_id,
                "chapter_node_id": record.chapter_node_id,
                "importance_level": record.importance_level,
                "difficulty_level": record.difficulty_level,
                "embedding_model": record.embedding_model,
                "content": record.content,
                "metadata": record.metadata,
                "embedding": record.embedding,
            }
        raise AppException(
            BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
            f"Milvus 集合 {collection_name} 暂未实现归一化写入逻辑",
        )

    def upsert_vectors(self, collection_name: str, records: list[VectorRecord]) -> dict[str, int]:
        """写入或更新向量数据。"""
        if not records:
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "待写入向量记录不能为空")
        self._ensure_supported_collection(collection_name)

        normalized_records = []
        for record in records:
            if len(record.embedding) != self.settings.milvus_embedding_dim:
                raise AppException(
                    BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                    "向量维度与配置不一致",
                    {"expected_dim": self.settings.milvus_embedding_dim, "actual_dim": len(record.embedding)},
                )
            normalized_records.append(self._normalize_record(collection_name, record))

        result = self.client.upsert(collection_name, normalized_records)
        return {"upsert_count": int(result.get("upsert_count", len(records)))}

    def delete_vectors(self, collection_name: str, ids: list[str]) -> dict[str, int]:
        """删除指定主键对应的向量。"""
        if not ids:
            return {"delete_count": 0}
        self._ensure_supported_collection(collection_name)
        result = self.client.delete(collection_name, ids)
        return {"delete_count": int(result.get("delete_count", len(ids)))}

    def search_vectors(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        filter_expression: str | None = None,
    ) -> list[VectorSearchHit]:
        """统一输出搜索结果。"""
        self._ensure_supported_collection(collection_name)
        if len(query_vector) != self.settings.milvus_embedding_dim:
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                "查询向量维度与配置不一致",
                {"expected_dim": self.settings.milvus_embedding_dim, "actual_dim": len(query_vector)},
            )

        results = self.client.search(collection_name, query_vector, limit, filter_expression)
        hits: list[VectorSearchHit] = []
        for item in results[0] if results else []:
            entity = item.get("entity", item)
            hits.append(
                VectorSearchHit(
                    id=str(item.get("id", entity.get("id", ""))),
                    score=float(item.get("distance", item.get("score", 0.0))),
                    collection_name=collection_name,
                    project_id=entity.get("project_id"),
                    embedding_model=entity.get("embedding_model"),
                    textbook_version_id=entity.get("textbook_version_id"),
                    parse_version_id=entity.get("parse_version_id"),
                    knowledge_version_id=entity.get("knowledge_version_id"),
                    chapter_node_id=entity.get("chapter_node_id"),
                    page_no=entity.get("page_no"),
                    block_type=entity.get("block_type"),
                    importance_level=entity.get("importance_level"),
                    difficulty_level=entity.get("difficulty_level"),
                    content=entity.get("content"),
                    metadata=entity.get("metadata"),
                )
            )
        return hits
