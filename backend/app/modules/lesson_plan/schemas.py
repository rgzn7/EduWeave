"""
@Date: 2026-05-04
@Author: xisy
@Discription: 教案模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.base import BaseSchema


def _validate_non_blank_string_list(values: list[str]) -> list[str]:
    """校验字符串列表不包含空内容。"""
    if any(not item.strip() for item in values):
        raise ValueError("列表内容不能为空")
    return values


class LessonPlanListItemResponse(BaseSchema):
    """教案列表项响应。"""

    id: int = Field(description="教案主键", examples=[1])
    curriculum_plan_id: int = Field(description="课程大纲主键", examples=[1])
    generation_batch_id: int | None = Field(default=None, description="生成批次主键")
    class_session_no: int | None = Field(default=None, description="批次内课次序号", examples=[1])
    version_no: int = Field(description="版本号", examples=[1])
    lesson_title: str = Field(description="教案标题", examples=["三年级数学乘法提升教案"])
    style_code: str | None = Field(default=None, description="教案风格编码", examples=["standard"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    summary_text: str | None = Field(default=None, description="教案摘要")
    content_json: dict[str, Any] = Field(description="教案结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class LessonPlanDetailResponse(LessonPlanListItemResponse):
    """教案详情响应。"""


class LessonPlanTeachingStepDraft(BaseSchema):
    """LLM 教案教学步骤草稿。"""

    step_no: int = Field(description="步骤序号", ge=1, examples=[1])
    stage_name: str = Field(description="教学环节名称", min_length=1, max_length=128, examples=["导入"])
    duration_minutes: int | None = Field(default=None, description="环节时长", ge=1, examples=[10])
    teacher_actions: list[str] = Field(description="教师动作", min_length=1)
    student_activities: list[str] = Field(description="学生活动", min_length=1)
    knowledge_point_refs: list[int] = Field(description="关联知识点主键列表", min_length=1)

    @field_validator("teacher_actions", "student_activities")
    @classmethod
    def validate_non_blank_string_items(cls, value: list[str]) -> list[str]:
        """校验教学动作不为空字符串。"""
        return _validate_non_blank_string_list(value)


class LessonPlanSessionDraft(BaseSchema):
    """LLM 教案课次草稿。"""

    session_no: int = Field(description="课次序号", ge=1, examples=[1])
    title: str = Field(description="课次标题", min_length=1, max_length=255, examples=["第1讲 乘法口诀训练"])
    objectives: list[str] = Field(description="课次目标", min_length=1)
    teaching_focus: list[str] = Field(description="教学重点", min_length=1)
    teaching_steps: list[LessonPlanTeachingStepDraft] = Field(description="教学步骤", min_length=1)
    homework: list[str] = Field(description="课后任务", min_length=1)
    knowledge_point_refs: list[int] = Field(description="关联知识点主键列表", min_length=1)

    @field_validator("objectives", "teaching_focus", "homework")
    @classmethod
    def validate_non_blank_string_items(cls, value: list[str]) -> list[str]:
        """校验课次文本列表不为空字符串。"""
        return _validate_non_blank_string_list(value)


class LessonPlanCourseOverview(BaseSchema):
    """LLM 教案课程概述。"""

    # 允许额外键：生成期模型常额外产出 teaching_style/learner_basis 等，
    # Agent 整体回写时若不保留会导致这些概述细节丢失。
    model_config = ConfigDict(extra="allow")

    audience: str = Field(description="授课对象描述", min_length=1, max_length=255)
    duration: str = Field(description="课时总安排描述", min_length=1, max_length=255)
    focus: str = Field(description="教学重点描述", min_length=1, max_length=255)


class LessonPlanAfterClassPlan(BaseSchema):
    """LLM 教案课后安排。"""

    review: str = Field(description="复习巩固安排", min_length=1, max_length=1024)
    homework: str = Field(description="课后作业安排", min_length=1, max_length=1024)
    parent_communication: str = Field(description="家校沟通安排", min_length=1, max_length=1024)


class LessonPlanGenerationResult(BaseSchema):
    """LLM 教案生成结果。"""

    lesson_title: str = Field(description="教案标题", min_length=1, max_length=255)
    summary_text: str | None = Field(default=None, description="教案摘要")
    course_overview: LessonPlanCourseOverview = Field(description="课程概述")
    material_list: list[str] = Field(description="物料清单", min_length=1)
    core_knowledge: list[str] = Field(description="核心知识", min_length=1)
    teaching_flow: list[LessonPlanTeachingStepDraft] = Field(description="标准行课流程", min_length=1)
    session_plans: list[LessonPlanSessionDraft] = Field(description="课次讲解安排", min_length=1)
    after_class_plan: LessonPlanAfterClassPlan = Field(description="课后安排")
    learner_adjustments: list[str] = Field(description="学情适配策略", min_length=1)
    knowledge_point_refs: list[int] = Field(description="教案整体关联知识点主键列表", min_length=1)

    @field_validator("material_list", "core_knowledge", "learner_adjustments")
    @classmethod
    def validate_non_blank_string_items(cls, value: list[str]) -> list[str]:
        """校验教案文本列表不为空字符串。"""
        return _validate_non_blank_string_list(value)

    @model_validator(mode="after")
    def validate_session_no_unique(self) -> "LessonPlanGenerationResult":
        """校验课次序号不重复。"""
        session_nos = [session.session_no for session in self.session_plans]
        if len(set(session_nos)) != len(session_nos):
            raise ValueError("课次序号不能重复")
        return self
