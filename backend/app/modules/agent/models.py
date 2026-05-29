"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手数据模型：会话、消息、运行、运行事件、运行工件
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.p0_models import (
    MYSQL_BIGINT_UNSIGNED,
    MYSQL_DATETIME_MS,
    MYSQL_JSON,
    MYSQL_MEDIUMTEXT,
    CreatedAtMixin,
    TimestampMixin,
)


class AgentSession(TimestampMixin, Base):
    """智能助手会话表。

    一个会话是一段对话线程，挂在某个项目下（项目级助手）。所在课次教案这类
    位置上下文不存在会话级，而是每次 Run 创建时由前端传入并落在 agent_run.context_json。
    """

    __tablename__ = "agent_session"
    __table_args__ = (
        Index("idx_agent_session_user", "user_id", "updated_at"),
        Index("idx_agent_session_project", "project_id", "updated_at"),
        {"comment": "智能助手会话表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=False,
        comment="所属教师",
    )
    project_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("project.id"),
        nullable=True,
        comment="所属项目（项目级助手范围；单页全局会话可为空）",
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="会话标题")


class AgentMessage(CreatedAtMixin, Base):
    """智能助手消息表（会话历史）。"""

    __tablename__ = "agent_message"
    __table_args__ = (
        Index("idx_agent_message_session", "session_id", "id"),
        Index("idx_agent_message_run", "run_id"),
        {"comment": "智能助手消息表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("agent_session.id"),
        nullable=False,
        comment="所属会话",
    )
    user_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=False, comment="所属教师")
    run_id: Mapped[int | None] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=True, comment="产出该消息的运行")
    role: Mapped[str] = mapped_column(String(32), nullable=False, comment="消息角色：user/assistant")
    content: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="消息内容")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="附加元数据")


class AgentRun(TimestampMixin, Base):
    """智能助手运行表（一次用户提交触发的 Agent 工具循环）。

    采用租约队列字段（status/available_at/locked_by/lease_expires_at）支撑后台 worker 抢占执行。
    context_json 固化本次运行的「所在课次教案」上下文，贯穿整个 run。
    """

    __tablename__ = "agent_run"
    __table_args__ = (
        Index("idx_agent_run_queue", "status", "available_at"),
        Index("idx_agent_run_session", "session_id", "id"),
        {"comment": "智能助手运行表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("agent_session.id"),
        nullable=False,
        comment="所属会话",
    )
    project_id: Mapped[int | None] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=True, comment="所属项目")
    user_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=False, comment="所属教师")
    user_message_id: Mapped[int | None] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=True, comment="触发运行的用户消息")
    assistant_message_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        nullable=True,
        comment="运行成功落库的助手消息",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="运行状态：pending/running/succeeded/failed/cancelled",
    )
    context_json: Mapped[dict[str, Any] | None] = mapped_column(
        MYSQL_JSON,
        nullable=True,
        comment="所在课次教案上下文：{project_id,curriculum_plan_id,class_session_no,lesson_plan_id}",
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="已尝试次数")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"), comment="最大尝试次数")
    available_at: Mapped[datetime] = mapped_column(MYSQL_DATETIME_MS, nullable=False, comment="可被抢占的时间")
    locked_by: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default=text("''"), comment="持锁 worker")
    lease_expires_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="租约过期时间")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="最近错误码")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近错误信息")
    final_response: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="最终回答文本")
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始执行时间")
    completed_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")


class AgentRunEvent(CreatedAtMixin, Base):
    """智能助手运行事件表（供 SSE 增量推送工具调用过程）。"""

    __tablename__ = "agent_run_event"
    __table_args__ = (
        Index("uk_agent_run_event_seq", "run_id", "seq", unique=True),
        {"comment": "智能助手运行事件表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("agent_run.id"),
        nullable=False,
        comment="所属运行",
    )
    session_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=False, comment="所属会话")
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="运行内自增序号")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="事件类型")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="事件标题")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="事件描述")
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="事件载荷")


class AgentArtifact(TimestampMixin, Base):
    """智能助手运行工件表（大段工具结果落库 + 去重 + 写后失效）。"""

    __tablename__ = "agent_artifact"
    __table_args__ = (
        Index("uk_agent_artifact_hash", "session_id", "source_tool", "content_hash", unique=True),
        Index("idx_agent_artifact_session", "session_id", "id"),
        {"comment": "智能助手运行工件表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("agent_session.id"),
        nullable=False,
        comment="所属会话",
    )
    source_tool: Mapped[str] = mapped_column(String(64), nullable=False, comment="来源工具名")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="内容哈希（去重）")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="工件标题")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="工件摘要预览")
    content_text: Mapped[str] = mapped_column(MYSQL_MEDIUMTEXT, nullable=False, comment="工件全文")
    superseded_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="失效时间")
