"""
@Date: 2026-05-26
@Author: xisy
@Discription: 一键生成编排模块请求与响应模型
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.base import BaseSchema

GenerationRunStatus = Literal[
    "pending",
    "running",
    "waiting_user_confirm",
    "succeeded",
    "failed",
    "cancelled",
]


class GenerationRunCreateRequest(BaseSchema):
    """一键生成创建请求。"""

    # 与 GenerationBatchCreateRequest 保持一致，避免编排里组装 batch 请求时被驳回
    course_count: int = Field(ge=1, le=120, description="课次数", examples=[10])
    session_duration_minutes: int = Field(ge=15, le=360, description="单次时长（分钟）", examples=[40])
    chapter_range_json: dict[str, Any] | None = Field(
        default=None,
        description="章节范围；省略表示全量",
    )
    auto_confirm_parse: bool = Field(
        default=True,
        description=(
            "教材解析成功后是否自动 confirm。默认开启，符合「一键生成」预期；"
            "若希望解析后人工校对后再继续下游，可显式传 false，"
            "此时 run 将进入 waiting_user_confirm 状态，用户在解析页确认后自动续跑。"
        ),
    )


class GenerationRunResponse(BaseSchema):
    """一键生成响应。"""

    id: int = Field(description="运行主键", examples=[1])
    project_id: int = Field(description="项目主键", examples=[1])
    run_status: GenerationRunStatus = Field(description="运行状态", examples=["running"])
    course_count: int = Field(description="课次数", examples=[10])
    session_duration_minutes: int = Field(description="单次时长（分钟）", examples=[40])
    chapter_range_json: dict[str, Any] | None = Field(default=None, description="章节范围")
    auto_confirm_parse: bool = Field(description="解析自动确认开关", examples=[True])
    parse_version_id: int | None = Field(default=None, description="使用的解析版本", examples=[1])
    knowledge_version_id: int | None = Field(default=None, description="使用的知识版本", examples=[1])
    generation_batch_id: int | None = Field(default=None, description="生成批次", examples=[1])
    blocked_reason: str | None = Field(default=None, description="阻塞原因编码")
    last_error_code: str | None = Field(default=None, description="错误码")
    last_error_message: str | None = Field(default=None, description="错误信息")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
