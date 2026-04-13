"""
@Date: 2026-04-11
@Author: xisy
@Discription: Milvus 向量服务封装
"""

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.vector.client import MilvusVectorClient
from app.shared.vector.schemas import VectorRecord, VectorSearchHit


class MilvusVectorService:
    """屏蔽 pymilvus 细节的向量服务层。"""

    def __init__(self, client: MilvusVectorClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or MilvusVectorClient(self.settings)

    def health_check(self) -> dict[str, str]:
        """执行 Milvus 健康检查。"""
        return self.client.health_check()

    def ensure_collections(self) -> list[str]:
        """引导初始化所有必需集合。"""
        return self.client.ensure_collections()

    def upsert_vectors(self, collection_name: str, records: list[VectorRecord]) -> dict[str, int]:
        """写入或更新向量数据。"""
        if not records:
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "待写入向量记录不能为空")

        normalized_records = []
        for record in records:
            if len(record.embedding) != self.settings.milvus_embedding_dim:
                raise AppException(
                    BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                    "向量维度与配置不一致",
                    {"expected_dim": self.settings.milvus_embedding_dim, "actual_dim": len(record.embedding)},
                )
            normalized_records.append(
                {
                    "id": record.id,
                    "source_id": record.source_id,
                    "source_type": record.source_type,
                    "project_id": record.project_id or 0,
                    "content": record.content or "",
                    "metadata": record.metadata or {},
                    "embedding": record.embedding,
                }
            )

        result = self.client.upsert(collection_name, normalized_records)
        return {"upsert_count": int(result.get("upsert_count", len(records)))}

    def delete_vectors(self, collection_name: str, ids: list[str]) -> dict[str, int]:
        """删除指定主键对应的向量。"""
        if not ids:
            return {"delete_count": 0}
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
                    id=str(item.get("id", "")),
                    score=float(item.get("distance", item.get("score", 0.0))),
                    source_id=entity.get("source_id"),
                    source_type=entity.get("source_type"),
                    project_id=entity.get("project_id"),
                    content=entity.get("content") or None,
                    metadata=entity.get("metadata") or None,
                )
            )
        return hits
