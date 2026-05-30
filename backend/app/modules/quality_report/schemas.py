"""
@Date: 2026-05-30
@Author: xisy
@Discription: 覆盖率分析模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class CoverageReportListItemResponse(BaseSchema):
    """覆盖率报告列表项响应。"""

    id: int = Field(description="覆盖率报告主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    report_status: str = Field(description="报告状态", examples=["success"])
    coverage_rate: float | None = Field(default=None, description="覆盖率百分比", examples=[100.0])
    warning_count: int = Field(description="告警数量", examples=[0])
    coverage_summary_json: dict[str, Any] | None = Field(default=None, description="覆盖摘要")
    report_json: dict[str, Any] = Field(description="覆盖率报告内容，包含覆盖矩阵、质量评审、学情适配和补救建议")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class CoverageReportDetailResponse(CoverageReportListItemResponse):
    """覆盖率报告详情响应。"""
