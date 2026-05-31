"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手请求与响应模型
"""

from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class AgentContextSchema(BaseSchema):
    """所在课次教案上下文（单页形态各字段可为空）。"""

    project_id: int | None = Field(default=None, description="所属项目主键")
    curriculum_plan_id: int | None = Field(default=None, description="所在课程大纲主键")
    class_session_no: int | None = Field(default=None, description="所在课次序号")
    lesson_plan_id: int | None = Field(default=None, description="所在教案主键")


class CreateSessionRequest(BaseSchema):
    """创建会话请求。"""

    project_id: int = Field(description="所属项目主键")
    title: str | None = Field(default=None, description="会话标题", max_length=255)


class AgentSessionResponse(BaseSchema):
    """会话响应。"""

    id: int = Field(description="会话主键")
    project_id: int | None = Field(default=None, description="所属项目主键")
    title: str | None = Field(default=None, description="会话标题")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class DeleteAgentSessionResponse(BaseSchema):
    """删除会话响应。"""

    session_id: int = Field(description="已删除会话主键")
    deleted_messages: int = Field(description="删除的消息数量")
    deleted_runs: int = Field(description="删除的运行数量")
    deleted_events: int = Field(description="删除的运行事件数量")
    deleted_artifacts: int = Field(description="删除的会话工件数量")


class CreateRunRequest(BaseSchema):
    """提交运行请求。"""

    content: str = Field(description="用户消息内容", min_length=1)
    context: AgentContextSchema | None = Field(default=None, description="所在课次教案上下文，贯穿本次运行")


class AgentRunResponse(BaseSchema):
    """运行响应。"""

    id: int = Field(description="运行主键")
    session_id: int = Field(description="所属会话主键")
    status: str = Field(description="运行状态")
    final_response: str | None = Field(default=None, description="最终回答文本")
    last_error_code: str | None = Field(default=None, description="最近错误码")
    error_message: str | None = Field(default=None, description="最近错误信息")
    created_at: datetime = Field(description="创建时间")
    started_at: datetime | None = Field(default=None, description="开始时间")
    completed_at: datetime | None = Field(default=None, description="结束时间")


class AgentMessageResponse(BaseSchema):
    """消息响应。"""

    id: int = Field(description="消息主键")
    role: str = Field(description="消息角色")
    content: str | None = Field(default=None, description="消息内容")
    run_id: int | None = Field(default=None, description="产出该消息的运行主键")
    created_at: datetime = Field(description="创建时间")
