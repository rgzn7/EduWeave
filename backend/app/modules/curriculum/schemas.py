"""
@Date: 2026-04-26
@Author: xisy
@Discription: 课程大纲模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import BaseSchema


class CurriculumPlanListItemResponse(BaseSchema):
    """课程大纲列表项响应。"""

    id: int = Field(description="课程大纲主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    knowledge_version_id: int = Field(description="知识版本主键", examples=[1])
    learner_profile_version_id: int = Field(description="学情版本主键", examples=[1])
    parent_plan_id: int | None = Field(default=None, description="父课程大纲主键")
    version_no: int = Field(description="版本号", examples=[1])
    plan_title: str = Field(description="课程大纲标题", examples=["三年级数学乘法提升课程"])
    target_subject_code: str = Field(description="目标学科编码", examples=["math"])
    target_grade_code: str | None = Field(default=None, description="目标年级编码")
    chapter_range_json: dict[str, Any] | None = Field(default=None, description="章节范围")
    course_count: int = Field(description="总课次", examples=[12])
    session_duration_minutes: int = Field(description="单次课时分钟数", examples=[90])
    generation_mode: str = Field(description="生成模式", examples=["ai"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    summary_text: str | None = Field(default=None, description="摘要")
    content_json: dict[str, Any] = Field(description="课程大纲结构化内容")
    export_file_id: int | None = Field(default=None, description="导出文件主键")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class CurriculumPlanDetailResponse(CurriculumPlanListItemResponse):
    """课程大纲详情响应。"""


class CurriculumLessonSessionDraft(BaseSchema):
    """LLM 课程课次草稿。"""

    session_no: int = Field(description="课次序号", ge=1, examples=[1])
    title: str = Field(description="课次标题", min_length=1, max_length=255, examples=["乘法口诀复习"])
    duration_minutes: int | None = Field(default=None, description="课次时长", ge=1, examples=[90])
    objectives: list[str] = Field(default_factory=list, description="课次目标")
    key_points: list[str] = Field(default_factory=list, description="课次重点")
    activities: list[str] = Field(default_factory=list, description="教学活动")
    homework: list[str] = Field(default_factory=list, description="课后任务")
    knowledge_point_refs: list[int] = Field(default_factory=list, description="关联知识点主键列表")


class CurriculumCourseOverview(BaseSchema):
    """LLM 课程大纲课程概览。"""

    # 允许额外键：生成期模型可能额外产出概览细节，Agent 整体回写时需保留，避免丢失。
    model_config = ConfigDict(extra="allow")

    audience: str = Field(description="课程对象描述", min_length=1, max_length=255)
    objective: str = Field(description="课程目标描述", min_length=1, max_length=255)
    duration: str = Field(description="课时总安排描述", min_length=1, max_length=255)


class CurriculumGenerationResult(BaseSchema):
    """LLM 课程大纲生成结果。"""

    plan_title: str = Field(description="课程大纲标题", min_length=1, max_length=255)
    summary_text: str | None = Field(default=None, description="课程大纲摘要")
    course_overview: CurriculumCourseOverview = Field(description="课程概览")
    stage_goals: list[str] = Field(default_factory=list, description="阶段目标")
    lesson_sessions: list[CurriculumLessonSessionDraft] = Field(description="课次安排", min_length=1)
    key_points: list[str] = Field(default_factory=list, description="课程重点")
    difficult_points: list[str] = Field(default_factory=list, description="课程难点")
    learner_adjustments: list[str] = Field(default_factory=list, description="学情适配策略")
    coverage_knowledge_points: list[int] = Field(default_factory=list, description="覆盖知识点主键列表")

    @model_validator(mode="after")
    def validate_session_no_unique(self) -> "CurriculumGenerationResult":
        """校验课次序号不重复。"""
        session_nos = [session.session_no for session in self.lesson_sessions]
        if len(set(session_nos)) != len(session_nos):
            raise ValueError("课次序号不能重复")
        session_ref_ids = {
            point_id
            for session in self.lesson_sessions
            for point_id in session.knowledge_point_refs
        }
        coverage_ids = set(self.coverage_knowledge_points)
        if coverage_ids != session_ref_ids:
            raise ValueError("coverage_knowledge_points 必须等于所有课次知识点引用并集")
        return self
