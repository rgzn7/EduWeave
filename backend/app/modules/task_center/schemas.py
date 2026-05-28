"""
@Date: 2026-05-28
@Author: xisy
@Discription: 任务中心模块请求与响应模型
"""

from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class TaskStepResponse(BaseSchema):
    """任务步骤响应。"""

    id: int = Field(description="步骤主键", examples=[1])
    step_code: str = Field(description="步骤编码", examples=["extract_profile"])
    step_name: str = Field(description="步骤名称", examples=["抽取学情占位结果"])
    step_order: int = Field(description="步骤顺序", examples=[1])
    step_status: str = Field(description="步骤状态", examples=["success"])
    progress_percent: int = Field(description="步骤进度", examples=[100])
    detail_json: dict | None = Field(default=None, description="步骤明细")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class TaskListItemResponse(BaseSchema):
    """任务列表项响应。"""

    id: int = Field(description="任务主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    generation_batch_id: int | None = Field(default=None, description="生成批次主键")
    module_code: str = Field(description="模块编码", examples=["parsing"])
    task_type: str = Field(description="任务类型", examples=["textbook_parse"])
    biz_key: str | None = Field(default=None, description="业务键", examples=["textbook_version:1:full"])
    task_status: str = Field(description="任务状态", examples=["success"])
    queue_name: str | None = Field(default=None, description="队列名称", examples=["parsing_queue"])
    current_stage: str | None = Field(default=None, description="当前阶段", examples=["save_parse_result"])
    progress_percent: int = Field(description="任务进度", examples=[100])
    retry_count: int = Field(description="重试次数", examples=[0])
    max_retry_count: int = Field(description="最大重试次数", examples=[3])
    worker_task_id: str | None = Field(default=None, description="Worker 任务ID")
    last_error_code: str | None = Field(default=None, description="最近错误码")
    last_error_message: str | None = Field(default=None, description="最近错误信息")
    payload_json: dict | None = Field(default=None, description="任务载荷")
    result_json: dict | None = Field(default=None, description="任务结果")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class TaskDetailResponse(TaskListItemResponse):
    """任务详情响应。"""

    steps: list[TaskStepResponse] = Field(description="任务步骤列表")
