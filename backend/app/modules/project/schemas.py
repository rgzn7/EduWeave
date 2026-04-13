"""
@Date: 2026-04-13
@Author: xisy
@Discription: 项目模块请求与响应模型
"""

from datetime import datetime

from pydantic import Field

from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.base import BaseSchema


class ProjectCreateRequest(BaseSchema):
    """创建项目请求。"""

    name: str = Field(description="项目名称", min_length=1, max_length=128, examples=["小学数学秋季提升班"])
    subject_code: str = Field(description="学科编码", min_length=1, max_length=32, examples=["math"])
    grade_code: str = Field(description="年级编码", min_length=1, max_length=32, examples=["grade_3"])
    applicable_target: str | None = Field(default=None, description="适用对象", max_length=255, examples=["三年级学生"])
    remark: str | None = Field(default=None, description="备注", max_length=500, examples=["主讲分数与几何基础"])
    project_code: str | None = Field(default=None, description="项目编码", max_length=64, examples=["math-g3-qiuji"])


class ProjectActiveRefsUpdateRequest(BaseSchema):
    """切换项目当前引用请求。"""

    current_textbook_version_id: int | None = Field(default=None, description="当前教材版本主键", examples=[1])
    current_learner_profile_version_id: int | None = Field(default=None, description="当前学情版本主键", examples=[1])


class ProjectCurrentTextbookResponse(BaseSchema):
    """当前教材引用摘要。"""

    id: int = Field(description="教材版本主键", examples=[1])
    version_no: int = Field(description="版本号", examples=[1])
    textbook_name: str = Field(description="教材名称", examples=["人民教育出版社三年级上册数学"])
    parse_status: str = Field(description="解析状态", examples=["pending"])


class ProjectCurrentLearnerProfileResponse(BaseSchema):
    """当前学情引用摘要。"""

    id: int = Field(description="学情版本主键", examples=[1])
    profile_file_id: int = Field(description="学情文件主键", examples=[1])
    version_no: int = Field(description="版本号", examples=[1])
    extract_status: str = Field(description="抽取状态", examples=["success"])
    summary_text: str | None = Field(default=None, description="摘要")


class ProjectListItemResponse(BaseSchema):
    """项目列表项响应。"""

    id: int = Field(description="项目主键", examples=[1])
    project_code: str | None = Field(default=None, description="项目编码")
    name: str = Field(description="项目名称", examples=["小学数学秋季提升班"])
    subject_code: str = Field(description="学科编码", examples=["math"])
    grade_code: str = Field(description="年级编码", examples=["grade_3"])
    applicable_target: str | None = Field(default=None, description="适用对象")
    remark: str | None = Field(default=None, description="备注")
    status: str = Field(description="项目状态", examples=["active"])
    current_textbook_version_id: int | None = Field(default=None, description="当前教材版本主键")
    current_learner_profile_version_id: int | None = Field(default=None, description="当前学情版本主键")
    latest_generation_batch_id: int | None = Field(default=None, description="最近生成批次主键")
    last_activity_at: datetime | None = Field(default=None, description="最近活动时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ProjectDetailResponse(ProjectListItemResponse):
    """项目详情响应。"""

    owner_user_id: int = Field(description="负责人主键", examples=[1])
    current_textbook: ProjectCurrentTextbookResponse | None = Field(default=None, description="当前教材引用")
    current_learner_profile: ProjectCurrentLearnerProfileResponse | None = Field(default=None, description="当前学情引用")


class ProjectDashboardStatsResponse(BaseSchema):
    """项目工作台统计。"""

    textbook_count: int = Field(description="教材数量", examples=[1])
    learner_profile_file_count: int = Field(description="学情文件数量", examples=[1])
    task_total_count: int = Field(description="任务总数", examples=[2])
    parsing_task_count: int = Field(description="解析任务总数", examples=[1])
    processing_task_count: int = Field(description="处理中任务数", examples=[0])
    failure_task_count: int = Field(description="失败任务数", examples=[0])


class ProjectDashboardResponse(BaseSchema):
    """项目工作台响应。"""

    project: ProjectDetailResponse = Field(description="项目详情")
    stats: ProjectDashboardStatsResponse = Field(description="工作台统计")
    recent_tasks: list[TaskListItemResponse] = Field(description="最近任务列表")
