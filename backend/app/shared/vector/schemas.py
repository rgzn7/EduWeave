"""
@Date: 2026-04-11
@Author: xisy
@Discription: Milvus 向量存储模型
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class VectorRecord(BaseModel):
    """统一向量写入记录。"""

    id: str = Field(description="主键标识")
    source_id: int = Field(description="来源主键")
    source_type: str = Field(description="来源类型")
    project_id: int | None = Field(default=None, description="项目主键")
    content: str | None = Field(default=None, description="文本内容")
    metadata: dict[str, Any] | None = Field(default=None, description="附加元数据")
    embedding: list[float] = Field(description="向量数据")

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
    source_id: int | None = None
    source_type: str | None = None
    project_id: int | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None

