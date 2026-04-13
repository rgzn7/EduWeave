"""
@Date: 2026-04-13
@Author: xisy
@Discription: Milvus 向量存储模型
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class VectorRecord(BaseModel):
    """统一向量写入记录。"""

    id: str = Field(description="主键标识")
    project_id: int = Field(description="项目主键")
    embedding_model: str = Field(description="Embedding 模型标识")
    textbook_version_id: int | None = Field(default=None, description="教材版本主键")
    parse_version_id: int | None = Field(default=None, description="解析版本主键")
    knowledge_version_id: int | None = Field(default=None, description="知识版本主键")
    chapter_node_id: int | None = Field(default=None, description="章节节点主键")
    page_no: int | None = Field(default=None, description="页码")
    block_type: str | None = Field(default=None, description="解析块类型")
    importance_level: int | None = Field(default=None, description="重要度")
    difficulty_level: int | None = Field(default=None, description="难度")
    content: str | None = Field(default=None, description="文本内容")
    metadata: dict[str, Any] | None = Field(default=None, description="附加元数据")
    embedding: list[float] = Field(description="向量数据")

    @field_validator("id", "embedding_model")
    @classmethod
    def validate_non_blank_string(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("字符串字段不能为空")
        return normalized_value

    @field_validator("block_type")
    @classmethod
    def validate_optional_block_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("块类型不能为空字符串")
        return normalized_value

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("向量内容不能为空")
        return value


class VectorSearchHit(BaseModel):
    """统一搜索结果模型。"""

    id: str
    score: float
    collection_name: str | None = None
    project_id: int | None = None
    embedding_model: str | None = None
    textbook_version_id: int | None = None
    parse_version_id: int | None = None
    knowledge_version_id: int | None = None
    chapter_node_id: int | None = None
    page_no: int | None = None
    block_type: str | None = None
    importance_level: int | None = None
    difficulty_level: int | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None
