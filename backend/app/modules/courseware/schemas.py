"""
@Date: 2026-05-03
@Author: xisy
@Discription: 课件模块请求与响应模型
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

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


class SlideExampleBlock(BaseSchema):
    """幻灯片例题块。"""

    stem_text: str = Field(description="例题题干", min_length=1)
    answer_text: str | None = Field(default=None, description="例题答案")
    analysis_text: str | None = Field(default=None, description="例题解析")


class SlideDraft(BaseSchema):
    """单页幻灯片结构。"""

    slide_no: int = Field(description="页序号", ge=1, examples=[1])
    slide_type: Literal[
        "cover",
        "toc",
        "knowledge",
        "example",
        "interaction",
        "summary",
        "homework",
    ] = Field(
        description="页型：cover/toc/knowledge/example/interaction/summary/homework",
        examples=["knowledge"],
    )
    title: str = Field(description="页标题", min_length=1, max_length=255, examples=["乘法分配律"])
    bullet_points: list[str] = Field(default_factory=list, description="页面要点")
    speaker_notes: str | None = Field(default=None, description="讲解备注")
    knowledge_point_refs: list[int] = Field(default_factory=list, description="关联知识点主键列表")
    example_block: SlideExampleBlock | None = Field(default=None, description="例题块（例题页使用）")

    @field_validator("bullet_points")
    @classmethod
    def validate_non_blank_bullets(cls, value: list[str]) -> list[str]:
        """校验要点不为空字符串。"""
        if any(not item.strip() for item in value):
            raise ValueError("要点内容不能为空")
        return value


class SlideDeckGenerationResult(BaseSchema):
    """LLM 结构化课件生成结果。"""

    deck_title: str = Field(description="课件标题", min_length=1, max_length=255)
    slides: list[SlideDraft] = Field(description="幻灯片列表", min_length=1)

    @model_validator(mode="after")
    def validate_slide_sequence(self) -> "SlideDeckGenerationResult":
        """校验页序号从 1 连续递增不重复且首页为封面。"""
        slide_nos = [slide.slide_no for slide in self.slides]
        if slide_nos != list(range(1, len(slide_nos) + 1)):
            raise ValueError("页序号必须从 1 开始连续递增且不重复")
        if self.slides[0].slide_type != "cover":
            raise ValueError("首页必须为封面页（cover）")
        return self


class CoursewareSlideDeckUpdateRequest(BaseSchema):
    """教师编辑课件结构请求。"""

    deck_title: str | None = Field(default=None, description="课件标题", max_length=255)
    slides: list[SlideDraft] = Field(description="编辑后的幻灯片列表", min_length=1)

    @model_validator(mode="after")
    def validate_slide_sequence(self) -> "CoursewareSlideDeckUpdateRequest":
        """校验页序号从 1 连续递增不重复且首页为封面。"""
        slide_nos = [slide.slide_no for slide in self.slides]
        if slide_nos != list(range(1, len(slide_nos) + 1)):
            raise ValueError("页序号必须从 1 开始连续递增且不重复")
        if self.slides[0].slide_type != "cover":
            raise ValueError("首页必须为封面页（cover）")
        return self
