"""
@Date: 2026-04-26
@Author: xisy
@Discription: 教案模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema


class LessonPlanListItemResponse(BaseSchema):
    """教案列表项响应。"""

    id: int = Field(description="教案主键", examples=[1])
    curriculum_plan_id: int = Field(description="课程大纲主键", examples=[1])
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
    teacher_actions: list[str] = Field(default_factory=list, description="教师动作")
    student_activities: list[str] = Field(default_factory=list, description="学生活动")
    knowledge_point_refs: list[int] = Field(default_factory=list, description="关联知识点主键列表")


class LessonPlanSessionDraft(BaseSchema):
    """LLM 教案课次草稿。"""

    session_no: int = Field(description="课次序号", ge=1, examples=[1])
    title: str = Field(description="课次标题", min_length=1, max_length=255, examples=["第1讲 乘法口诀训练"])
    objectives: list[str] = Field(default_factory=list, description="课次目标")
    teaching_focus: list[str] = Field(default_factory=list, description="教学重点")
    teaching_steps: list[LessonPlanTeachingStepDraft] = Field(default_factory=list, description="教学步骤")
    homework: list[str] = Field(default_factory=list, description="课后任务")
    knowledge_point_refs: list[int] = Field(default_factory=list, description="关联知识点主键列表")


class LessonPlanGenerationResult(BaseSchema):
    """LLM 教案生成结果。"""

    lesson_title: str = Field(description="教案标题", min_length=1, max_length=255)
    summary_text: str | None = Field(default=None, description="教案摘要")
    course_overview: dict[str, Any] = Field(default_factory=dict, description="课程概述")
    material_list: list[str] = Field(default_factory=list, description="物料清单")
    core_knowledge: list[str] = Field(default_factory=list, description="核心知识")
    teaching_flow: list[LessonPlanTeachingStepDraft] = Field(default_factory=list, description="标准行课流程")
    session_plans: list[LessonPlanSessionDraft] = Field(default_factory=list, description="课次讲解安排")
    after_class_plan: dict[str, Any] = Field(default_factory=dict, description="课后安排")
    learner_adjustments: list[str] = Field(default_factory=list, description="学情适配策略")
    knowledge_point_refs: list[int] = Field(default_factory=list, description="教案整体关联知识点主键列表")

    @model_validator(mode="after")
    def validate_session_no_unique(self) -> "LessonPlanGenerationResult":
        """校验课次序号不重复。"""
        session_nos = [session.session_no for session in self.session_plans]
        if len(set(session_nos)) != len(session_nos):
            raise ValueError("课次序号不能重复")
        return self

