"""
@Date: 2026-04-29
@Author: xisy
@Discription: 测评模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.schemas.base import BaseSchema

SUPPORTED_ASSESSMENT_QUESTION_TYPES = {"single_choice", "fill_blank", "short_answer"}


class AssessmentBlueprintListItemResponse(BaseSchema):
    """测评蓝图列表项响应。"""

    id: int = Field(description="测评蓝图主键", examples=[1])
    curriculum_plan_id: int = Field(description="课程大纲主键", examples=[1])
    version_no: int = Field(description="版本号", examples=[1])
    scenario_type: str = Field(description="测评场景类型", examples=["unit_test"])
    blueprint_name: str = Field(description="测评蓝图名称", examples=["乘法单元测试蓝图"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    strategy_json: dict[str, Any] | None = Field(default=None, description="测评策略配置")
    content_json: dict[str, Any] = Field(description="测评蓝图结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class AssessmentBlueprintDetailResponse(AssessmentBlueprintListItemResponse):
    """测评蓝图详情响应。"""


class QuestionItemResponse(BaseSchema):
    """题目明细响应。"""

    id: int = Field(description="题目主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    paper_result_id: int = Field(description="试卷结果主键", examples=[1])
    knowledge_point_id: int | None = Field(default=None, description="知识点主键")
    question_no: int = Field(description="题号", examples=[1])
    question_type: str = Field(description="题型", examples=["single_choice"])
    difficulty_level: int | None = Field(default=None, description="难度等级")
    score_value: float | None = Field(default=None, description="分值")
    stem_text: str = Field(description="题干")
    options_json: dict[str, Any] | None = Field(default=None, description="选项")
    answer_text: str | None = Field(default=None, description="答案")
    analysis_text: str | None = Field(default=None, description="解析")
    source_trace_json: dict[str, Any] | None = Field(default=None, description="来源摘要")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class PaperResultListItemResponse(BaseSchema):
    """试卷结果列表项响应。"""

    id: int = Field(description="试卷结果主键", examples=[1])
    generation_batch_id: int = Field(description="生成批次主键", examples=[1])
    assessment_blueprint_id: int = Field(description="测评蓝图主键", examples=[1])
    scene_type: str = Field(description="试卷场景类型", examples=["unit_test"])
    title: str = Field(description="试卷标题", examples=["乘法单元测试"])
    result_status: str = Field(description="结果状态", examples=["success"])
    question_count: int = Field(description="题目数量", examples=[10])
    difficulty_stats_json: dict[str, Any] | None = Field(default=None, description="难度统计")
    paper_json: dict[str, Any] = Field(description="试卷结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class PaperResultDetailResponse(PaperResultListItemResponse):
    """试卷结果详情响应。"""

    questions: list[QuestionItemResponse] = Field(default_factory=list, description="题目明细列表")


class AssessmentKnowledgeWeightDraft(BaseSchema):
    """LLM 测评知识点权重草稿。"""

    knowledge_point_id: int = Field(description="知识点主键", examples=[1])
    weight_percent: float | None = Field(default=None, ge=0, le=100, description="考查权重百分比")
    suggested_question_count: int = Field(default=1, ge=0, description="建议题量")
    question_types: list[str] = Field(default_factory=list, description="建议题型")
    difficulty_range: list[int] = Field(default_factory=list, description="建议难度范围")


class AssessmentQuestionDraft(BaseSchema):
    """LLM 测评题目草稿。"""

    question_no: int = Field(description="题号", ge=1, examples=[1])
    knowledge_point_id: int = Field(description="知识点主键", examples=[1])
    question_type: str = Field(description="题型", examples=["single_choice"])
    difficulty_level: int = Field(description="难度等级", ge=1, le=5, examples=[3])
    score_value: float | None = Field(default=None, ge=0, description="分值")
    stem_text: str = Field(description="题干", min_length=1)
    options_json: dict[str, Any] | None = Field(default=None, description="选项")
    answer_text: str = Field(description="答案", min_length=1)
    analysis_text: str = Field(description="解析", min_length=1)
    source_trace_json: dict[str, Any] | None = Field(default=None, description="来源摘要")

    @field_validator("question_type")
    @classmethod
    def validate_question_type(cls, value: str) -> str:
        """校验题型在 P0 默认支持范围内。"""
        if value not in SUPPORTED_ASSESSMENT_QUESTION_TYPES:
            raise ValueError("题型不在支持范围内")
        return value


class AssessmentGenerationResult(BaseSchema):
    """LLM 测评生成结果。"""

    blueprint_name: str = Field(description="测评蓝图名称", min_length=1, max_length=255)
    paper_title: str = Field(description="试卷标题", min_length=1, max_length=255)
    strategy_summary: dict[str, Any] = Field(default_factory=dict, description="策略摘要")
    knowledge_weights: list[AssessmentKnowledgeWeightDraft] = Field(description="知识点考查权重", min_length=1)
    question_type_distribution: dict[str, int] = Field(default_factory=dict, description="题型分布")
    difficulty_distribution: dict[str, int] = Field(default_factory=dict, description="难度分布")
    questions: list[AssessmentQuestionDraft] = Field(description="题目列表", min_length=1)

    @model_validator(mode="after")
    def validate_question_no_sequence(self) -> "AssessmentGenerationResult":
        """校验题号连续递增。"""
        question_nos = [question.question_no for question in self.questions]
        expected_nos = list(range(1, len(question_nos) + 1))
        if question_nos != expected_nos:
            raise ValueError("题号必须从 1 开始连续递增")
        return self
