"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class HomeworkBlueprintResponse(BaseSchema):
    """作业蓝图响应。"""

    id: int = Field(description="作业蓝图主键", examples=[1])
    lesson_plan_id: int = Field(description="所属教案主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    version_no: int = Field(description="版本号", examples=[1])
    blueprint_name: str = Field(description="作业蓝图名称", examples=["第 1 课课后作业蓝图"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    strategy_json: dict[str, Any] | None = Field(default=None, description="策略配置")
    content_json: dict[str, Any] = Field(description="蓝图结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class HomeworkQuestionResponse(BaseSchema):
    """作业题目响应。"""

    id: int = Field(description="作业题目主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    homework_result_id: int = Field(description="作业结果主键", examples=[1])
    lesson_plan_id: int = Field(description="所属教案主键", examples=[1])
    knowledge_point_id: int | None = Field(default=None, description="知识点主键")
    knowledge_point_name: str | None = Field(default=None, description="知识点名称，前端考查标签使用")
    question_no: int = Field(description="题号", examples=[1])
    question_type: str = Field(description="题型", examples=["single_choice"])
    difficulty_level: int | None = Field(default=None, description="难度等级")
    score_value: float | None = Field(default=None, description="分值")
    stem_text: str = Field(description="题干")
    options_json: dict[str, Any] | None = Field(default=None, description="选项")
    answer_text: str | None = Field(default=None, description="答案")
    analysis_text: str | None = Field(default=None, description="解析")
    source_trace_json: dict[str, Any] | None = Field(default=None, description="来源摘要")
    question_basis_json: dict[str, Any] | None = Field(
        default=None,
        description="题目考查依据：包含知识点、章节、课次、教学目标、测评定位、依据说明与蓝图来源",
    )
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class HomeworkQuestionListItemResponse(HomeworkQuestionResponse):
    """作业题目列表项响应。"""

    homework_title: str = Field(description="所属作业标题", examples=["第 1 课课后作业"])
    class_session_no: int | None = Field(default=None, description="所属课次序号", examples=[1])


class HomeworkResultListItemResponse(BaseSchema):
    """作业结果列表项响应。"""

    id: int = Field(description="作业结果主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    lesson_plan_id: int = Field(description="所属教案主键", examples=[1])
    homework_blueprint_id: int = Field(description="作业蓝图主键", examples=[1])
    title: str = Field(description="作业标题", examples=["第 1 课课后作业"])
    result_status: str = Field(description="结果状态", examples=["success"])
    question_count: int = Field(description="题目数量", examples=[6])
    difficulty_stats_json: dict[str, Any] | None = Field(default=None, description="难度统计")
    content_json: dict[str, Any] = Field(description="作业结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    class_session_no: int | None = Field(default=None, description="所属课次序号", examples=[1])
    lesson_title: str | None = Field(default=None, description="所属教案标题", examples=["第 1 课 集合的概念"])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class HomeworkResultDetailResponse(HomeworkResultListItemResponse):
    """作业结果详情响应。"""

    questions: list[HomeworkQuestionResponse] = Field(default_factory=list, description="题目明细列表")
