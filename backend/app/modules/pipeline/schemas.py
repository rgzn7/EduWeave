"""
@Date: 2026-05-04
@Author: xisy
@Discription: 生成编排模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.base import BaseSchema


class GenerationBatchCreateRequest(BaseSchema):
    """创建生成批次请求。"""

    project_id: int = Field(description="项目主键", examples=[1])
    knowledge_version_id: int = Field(description="知识版本主键", examples=[1])
    learner_profile_version_id: int = Field(description="学情版本主键", examples=[1])
    batch_name: str | None = Field(default=None, description="批次名称", max_length=255, examples=["第一轮课程规划"])
    chapter_range_json: dict[str, Any] | None = Field(
        default=None,
        description="章节范围快照；缺省或 chapter_node_ids 为空表示全量，非空 chapter_node_ids 表示选中章节及其子章节",
        examples=[{"chapter_node_ids": [1, 2]}],
    )
    course_count: int = Field(description="总课次", ge=1, le=120, examples=[12])
    session_duration_minutes: int = Field(description="单次课时分钟数", ge=15, le=360, examples=[90])


class GenerationBatchListItemResponse(BaseSchema):
    """生成批次列表项响应。"""

    id: int = Field(description="生成批次主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    batch_no: int = Field(description="项目内批次号", examples=[1])
    batch_name: str | None = Field(default=None, description="批次名称")
    trigger_mode: str = Field(description="触发模式", examples=["manual"])
    batch_status: str = Field(description="批次状态", examples=["success"])
    knowledge_version_id: int = Field(description="知识版本主键", examples=[1])
    learner_profile_version_id: int = Field(description="学情版本主键", examples=[1])
    chapter_range_json: dict[str, Any] | None = Field(default=None, description="章节范围快照")
    course_count: int | None = Field(default=None, description="总课次快照")
    session_duration_minutes: int | None = Field(default=None, description="单次课时分钟数快照")
    template_snapshot_json: dict[str, Any] | None = Field(default=None, description="模板快照")
    assessment_strategy_json: dict[str, Any] | None = Field(default=None, description="测评策略快照")
    pipeline_options_json: dict[str, Any] | None = Field(default=None, description="编排选项")
    curriculum_plan_id: int | None = Field(default=None, description="课程大纲版本主键")
    lesson_plan_id: int | None = Field(default=None, description="教案版本主键")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class GenerationBatchDetailResponse(GenerationBatchListItemResponse):
    """生成批次详情响应。"""

    lesson_plan_ids: list[int] = Field(default_factory=list, description="批次下全部教案主键列表")
    tasks: list[TaskListItemResponse] = Field(default_factory=list, description="批次关联任务列表")
