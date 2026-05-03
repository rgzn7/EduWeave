"""
@Date: 2026-05-03
@Author: xisy
@Discription: 课件模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class CoursewareResultListItemResponse(BaseSchema):
    """课件结果列表项响应。"""

    id: int = Field(description="课件结果主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    lesson_plan_id: int = Field(description="教案版本主键", examples=[1])
    template_code: str | None = Field(default=None, description="模板编码")
    template_version: str | None = Field(default=None, description="模板版本")
    result_status: str = Field(description="课件结果状态", examples=["success"])
    page_count: int | None = Field(default=None, description="页数")
    page_type_stats_json: dict[str, Any] | None = Field(default=None, description="页面类型统计")
    structure_json: dict[str, Any] = Field(description="课件结构与生成摘要")
    preview_json: dict[str, Any] | None = Field(default=None, description="远程任务预览状态")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class CoursewareResultDetailResponse(CoursewareResultListItemResponse):
    """课件结果详情响应。"""


class CoursewareReplyRequest(BaseSchema):
    """回复 Raccoon PPT 补充问题请求。"""

    answer: str = Field(description="补充回答内容", min_length=1, max_length=2000, examples=["请按三年级学生水平简化例题。"])
