"""
@Date: 2026-04-14
@Author: xisy
@Discription: 学情模块请求与响应模型
"""

from datetime import datetime
from typing import Annotated

from fastapi import Form
from pydantic import Field

from app.modules.textbook.schemas import FileObjectSummaryResponse
from app.schemas.base import BaseSchema


class LearnerProfileUploadRequest(BaseSchema):
    """班级学情上传请求（一次上传多份学生 docx）。"""

    title: str | None = Field(default=None, description="班级名称", examples=["三年级一班"])
    grade_code: str | None = Field(default=None, description="年级编码", examples=["grade_6"])
    subject_scope: str | None = Field(default=None, description="学科范围", examples=["english,math"])
    textbook_version_hint_id: int | None = Field(default=None, description="教材提示版本主键", examples=[1])
    auto_extract: bool = Field(default=True, description="是否立即创建抽取任务", examples=[True])
    set_as_current: bool = Field(default=False, description="是否在成功后设为当前学情版本", examples=[True])

    @classmethod
    def as_form(
        cls,
        title: Annotated[str | None, Form(description="班级名称", examples=["三年级一班"])] = None,
        grade_code: Annotated[str | None, Form(description="年级编码", examples=["grade_6"])] = None,
        subject_scope: Annotated[str | None, Form(description="学科范围", examples=["english,math"])] = None,
        textbook_version_hint_id: Annotated[int | None, Form(description="教材提示版本主键", examples=[1])] = None,
        auto_extract: Annotated[bool, Form(description="是否立即创建抽取任务", examples=[True])] = True,
        set_as_current: Annotated[bool, Form(description="是否在成功后设为当前学情版本", examples=[True])] = False,
    ) -> "LearnerProfileUploadRequest":
        """将 multipart/form-data 字段转换为学情上传请求模型。"""
        return cls(
            title=title,
            grade_code=grade_code,
            subject_scope=subject_scope,
            textbook_version_hint_id=textbook_version_hint_id,
            auto_extract=auto_extract,
            set_as_current=set_as_current,
        )


class LearnerProfileManualRevisionRecordRequest(BaseSchema):
    """学情画像人工修正记录请求。"""

    student_key: str = Field(description="学生标识", min_length=1, max_length=128, examples=["王xx_math"])
    student_name: str | None = Field(default=None, description="学生姓名", examples=["王xx"])
    is_anonymous: bool = Field(default=False, description="是否匿名", examples=[False])
    region_name: str | None = Field(default=None, description="地区名称", examples=["上海"])
    grade_code: str | None = Field(default=None, description="年级编码", examples=["grade_3"])
    subject_code: str = Field(description="学科编码", min_length=1, max_length=32, examples=["math"])
    textbook_version_hint_id: int | None = Field(default=None, description="教材提示版本主键", examples=[1])
    score_value: float | None = Field(default=None, description="分数", examples=[82.0])
    advantage_tags_json: dict | None = Field(default=None, description="优势标签", examples=[{"items": ["表达能力较强"]}])
    weakness_tags_json: dict | None = Field(default=None, description="薄弱标签", examples=[{"items": ["口语表达待提升"]}])
    ability_tags_json: dict | None = Field(default=None, description="能力标签", examples=[{"items": ["表达能力"]}])
    habit_tags_json: dict | None = Field(default=None, description="学习习惯标签", examples=[{"items": ["作业完成及时"]}])
    behavior_traits_json: dict | None = Field(default=None, description="行为特征标签", examples=[{"items": ["性格开朗"]}])
    time_plan_json: dict | None = Field(
        default=None,
        description="时间规划标签",
        examples=[{"items": [{"subject_name": "英语", "weekly_hours": 3}]}],
    )
    summary_text: str | None = Field(default=None, description="摘要文本", examples=["英语人工修正摘要"])
    evidence_json: dict | None = Field(default=None, description="证据 JSON", examples=[{"source": "manual"}])
    sort_order: int = Field(default=0, description="排序号", ge=0, examples=[0])


class LearnerProfileManualRevisionRequest(BaseSchema):
    """学情版本人工修正请求。"""

    summary_text: str | None = Field(default=None, description="版本摘要", examples=["人工修正后的学情摘要"])
    grade_code: str | None = Field(default=None, description="年级编码", examples=["grade_3"])
    subject_scope: str | None = Field(default=None, description="学科范围", examples=["english,math"])
    records: list[LearnerProfileManualRevisionRecordRequest] = Field(
        description="完整画像记录列表",
        min_length=1,
        examples=[
            [
                {
                    "student_key": "wangxx_english",
                    "student_name": "王xx",
                    "is_anonymous": True,
                    "region_name": "上海",
                    "grade_code": "grade_3",
                    "subject_code": "english",
                    "score_value": 88,
                    "advantage_tags_json": {"items": ["表达能力较强"]},
                    "weakness_tags_json": {"items": ["口语表达待提升"]},
                    "ability_tags_json": {"items": ["表达能力"]},
                    "habit_tags_json": {"items": ["作业完成及时"]},
                    "behavior_traits_json": {"items": ["性格开朗"]},
                    "time_plan_json": {"items": [{"subject_name": "英语", "weekly_hours": 3}]},
                    "summary_text": "英语人工修正摘要",
                    "evidence_json": {"source": "manual"},
                    "sort_order": 0,
                }
            ]
        ],
    )
    set_as_current: bool = Field(default=False, description="是否设为项目当前学情版本", examples=[True])


class LearnerProfileRecordResponse(BaseSchema):
    """学情画像记录响应。"""

    id: int = Field(description="画像记录主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    profile_version_id: int = Field(description="学情版本主键", examples=[1])
    student_key: str = Field(description="学生标识", examples=["王xx_math"])
    student_name: str | None = Field(default=None, description="学生姓名")
    is_anonymous: bool = Field(description="是否匿名", examples=[False])
    region_name: str | None = Field(default=None, description="地区名称")
    grade_code: str | None = Field(default=None, description="年级编码")
    subject_code: str = Field(description="学科编码", examples=["math"])
    textbook_version_hint_id: int | None = Field(default=None, description="教材提示版本主键")
    score_value: float | None = Field(default=None, description="分数")
    advantage_tags_json: dict | None = Field(default=None, description="优势标签")
    weakness_tags_json: dict | None = Field(default=None, description="薄弱标签")
    ability_tags_json: dict | None = Field(default=None, description="能力标签")
    habit_tags_json: dict | None = Field(default=None, description="学习习惯标签")
    behavior_traits_json: dict | None = Field(default=None, description="行为特征")
    time_plan_json: dict | None = Field(default=None, description="时间规划")
    summary_text: str | None = Field(default=None, description="摘要文本")
    evidence_json: dict | None = Field(default=None, description="原文依据")
    sort_order: int = Field(description="排序号", examples=[0])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class LearnerProfileVersionListItemResponse(BaseSchema):
    """学情版本列表项响应。"""

    id: int = Field(description="学情版本主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    profile_file_id: int = Field(description="学情文件主键", examples=[1])
    parent_version_id: int | None = Field(default=None, description="父版本主键")
    version_no: int = Field(description="版本号", examples=[1])
    textbook_version_hint_id: int | None = Field(default=None, description="教材提示版本主键")
    grade_code: str | None = Field(default=None, description="年级编码")
    subject_scope: str | None = Field(default=None, description="学科范围")
    extract_status: str = Field(description="抽取状态", examples=["success"])
    review_status: str = Field(description="审核状态", examples=["pending"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    summary_text: str | None = Field(default=None, description="摘要文本（班级整体学情摘要）")
    class_profile: dict | None = Field(default=None, description="班级画像聚合结果（学科概览、共性强弱、分层建议等）")
    raw_result_json: dict | None = Field(default=None, description="抽取结果 JSON")
    source_snapshot_json: dict | None = Field(default=None, description="输入快照")
    created_by: int | None = Field(default=None, description="创建人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class LearnerProfileVersionResponse(LearnerProfileVersionListItemResponse):
    """学情版本响应。"""

    records: list[LearnerProfileRecordResponse] = Field(description="画像记录列表")


class LearnerProfileFileListItemResponse(BaseSchema):
    """学情文件列表项响应。"""

    id: int = Field(description="学情文件主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    source_file_id: int = Field(description="源文件主键", examples=[1])
    title: str = Field(description="学情文档标题", examples=["学生1学情分析"])
    file_status: str = Field(description="文件状态", examples=["success"])
    source_file: FileObjectSummaryResponse = Field(description="源文件摘要")
    latest_version: LearnerProfileVersionResponse | None = Field(default=None, description="最新学情版本")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class LearnerProfileFileDetailResponse(LearnerProfileFileListItemResponse):
    """学情文件详情响应。"""
