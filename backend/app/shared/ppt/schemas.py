"""
@Date: 2026-05-03
@Author: xisy
@Discription: Raccoon PPT 适配层结构模型
"""

from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class RaccoonPptJobState(BaseSchema):
    """Raccoon PPT 任务状态。"""

    job_id: str = Field(description="远程 PPT 任务ID")
    status: str = Field(description="远程任务状态")
    download_url: str | None = Field(default=None, description="PPTX 下载地址")
    required_user_input: str | None = Field(default=None, description="需要用户补充的问题")
    error_message: str | None = Field(default=None, description="远程失败原因")
    raw_payload: dict[str, Any] = Field(default_factory=dict, description="远程原始响应")


class RaccoonPptCreateRequest(BaseSchema):
    """创建 Raccoon PPT 任务请求。"""

    prompt: str = Field(description="课件生成提示词")
    role: str = Field(default="教师", description="生成角色")
    scene: str = Field(default="培训教学", description="生成场景")
    audience: str = Field(default="学生", description="目标受众")
