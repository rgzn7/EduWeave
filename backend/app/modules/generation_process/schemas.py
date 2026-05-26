"""
@Date: 2026-05-26
@Author: xisy
@Discription: 生成过程展示模块请求与响应模型
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import BaseSchema

GenerationProcessStatus = Literal["pending", "running", "succeeded", "failed", "waiting"]


class GenerationProcessStepResponse(BaseSchema):
    """生成过程展示步骤响应。"""

    code: str = Field(description="展示步骤编码", examples=["mineru_parse"])
    display_name: str = Field(description="展示步骤名称", examples=["调用 MinerU 教材解析工具"])
    description: str = Field(
        description="展示步骤说明",
        examples=["识别教材章节、页码、图表、题目和知识点。"],
    )
    status: GenerationProcessStatus = Field(description="展示状态", examples=["running"])
    progress_percent: int = Field(description="进度百分比", examples=[60])
    summary: str | None = Field(default=None, description="面向用户的步骤摘要", examples=["已识别 12 页教材内容。"])
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    error_message: str | None = Field(
        default=None,
        description="面向用户的错误文案，仅失败时返回",
        examples=["教材解析失败，请确认上传文件是否为清晰的 PDF。"],
    )


class GenerationProcessResponse(BaseSchema):
    """生成过程展示响应。"""

    project_id: int = Field(description="项目主键", examples=[1])
    batch_id: int | None = Field(default=None, description="最近一次生成批次主键", examples=[1])
    status: GenerationProcessStatus = Field(description="整体展示状态", examples=["running"])
    current_step_code: str | None = Field(
        default=None,
        description="当前正在进行的展示步骤编码",
        examples=["lesson_plan_generate"],
    )
    steps: list[GenerationProcessStepResponse] = Field(description="展示步骤列表，固定 6 步")
