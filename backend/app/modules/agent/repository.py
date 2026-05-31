"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手数据访问层：会话/消息/运行/运行事件/运行工件
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.agent.models import (
    AgentArtifact,
    AgentMessage,
    AgentRun,
    AgentRunEvent,
    AgentSession,
)
from app.shared.utils.datetime_util import DateTimeUtil


class AgentRepository:
    """智能助手模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def create_session(self, *, user_id: int, project_id: int | None, title: str | None) -> AgentSession:
        """创建会话。"""
        record = AgentSession(user_id=user_id, project_id=project_id, title=title)
        self.session.add(record)
        self.session.flush()
        return record

    def get_session_for_owner(self, session_id: int, user_id: int) -> AgentSession | None:
        """查询当前教师可见的会话。"""
        statement = select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user_id)
        return self.session.scalar(statement)

    def list_sessions_for_owner(
        self,
        user_id: int,
        *,
        project_id: int | None,
        offset: int,
        limit: int,
    ) -> list[AgentSession]:
        """分页查询当前教师的会话。"""
        statement = select(AgentSession).where(AgentSession.user_id == user_id)
        if project_id is not None:
            statement = statement.where(AgentSession.project_id == project_id)
        statement = statement.order_by(AgentSession.updated_at.desc(), AgentSession.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def touch_session(self, session_id: int) -> None:
        """刷新会话更新时间，使其排到列表前部。"""
        self.session.execute(
            update(AgentSession).where(AgentSession.id == session_id).values(updated_at=DateTimeUtil.now_utc())
        )

    # ------------------------------------------------------------------ #
    # 消息
    # ------------------------------------------------------------------ #
    def create_message(
        self,
        *,
        session_id: int,
        user_id: int,
        role: str,
        content: str | None,
        run_id: int | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """创建消息。"""
        record = AgentMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            run_id=run_id,
            metadata_json=metadata_json,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_messages(self, session_id: int, *, limit: int) -> list[AgentMessage]:
        """读取会话最近消息（按时间升序返回）。"""
        statement = (
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.id.desc())
            .limit(limit)
        )
        records = list(self.session.scalars(statement))
        records.reverse()
        return records

    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def create_run(
        self,
        *,
        session_id: int,
        project_id: int | None,
        user_id: int,
        user_message_id: int,
        context_json: dict[str, Any] | None,
        max_attempts: int,
    ) -> AgentRun:
        """创建运行并入队。"""
        record = AgentRun(
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            user_message_id=user_message_id,
            context_json=context_json,
            status="pending",
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=DateTimeUtil.now_utc(),
            locked_by="",
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_run(self, run_id: int) -> AgentRun | None:
        """按主键查询运行。"""
        return self.session.scalar(select(AgentRun).where(AgentRun.id == run_id))

    def get_run_for_owner(self, run_id: int, user_id: int) -> AgentRun | None:
        """查询当前教师可见的运行。"""
        return self.session.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))

    # ------------------------------------------------------------------ #
    # 运行事件
    # ------------------------------------------------------------------ #
    def next_event_seq(self, run_id: int) -> int:
        """计算运行内下一个事件序号。"""
        current_max = self.session.scalar(select(func.max(AgentRunEvent.seq)).where(AgentRunEvent.run_id == run_id))
        return int(current_max or 0) + 1

    def add_event(
        self,
        *,
        run_id: int,
        session_id: int,
        event_type: str,
        title: str | None,
        message: str | None,
        payload_json: dict[str, Any] | None,
    ) -> AgentRunEvent:
        """追加运行事件。"""
        record = AgentRunEvent(
            run_id=run_id,
            session_id=session_id,
            seq=self.next_event_seq(run_id),
            event_type=event_type,
            title=title,
            message=message,
            payload_json=payload_json,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_events(self, run_id: int, *, after_seq: int) -> list[AgentRunEvent]:
        """读取运行的增量事件。"""
        statement = (
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id, AgentRunEvent.seq > after_seq)
            .order_by(AgentRunEvent.seq.asc())
        )
        return list(self.session.scalars(statement))

    # ------------------------------------------------------------------ #
    # 运行工件
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_content_hash(content_text: str) -> str:
        """计算工件内容哈希。"""
        return hashlib.sha256(content_text.encode("utf-8")).hexdigest()

    def create_or_reuse_artifact(
        self,
        *,
        session_id: int,
        source_tool: str,
        content_text: str,
        title: str | None,
        summary: str | None,
    ) -> AgentArtifact:
        """按 (会话, 工具, 内容哈希) 去重创建工件。"""
        content_hash = self.compute_content_hash(content_text)
        existing = self.session.scalar(
            select(AgentArtifact).where(
                AgentArtifact.session_id == session_id,
                AgentArtifact.source_tool == source_tool,
                AgentArtifact.content_hash == content_hash,
            )
        )
        if existing is not None:
            if existing.superseded_at is not None:
                existing.superseded_at = None
                self.session.add(existing)
                self.session.flush()
            return existing
        record = AgentArtifact(
            session_id=session_id,
            source_tool=source_tool,
            content_hash=content_hash,
            title=title,
            summary=summary,
            content_text=content_text,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_active_artifact(self, session_id: int, artifact_id: int) -> AgentArtifact | None:
        """读取会话内未失效的工件。"""
        return self.session.scalar(
            select(AgentArtifact).where(
                AgentArtifact.id == artifact_id,
                AgentArtifact.session_id == session_id,
                AgentArtifact.superseded_at.is_(None),
            )
        )

    def list_active_artifacts(self, session_id: int) -> list[AgentArtifact]:
        """读取会话内全部未失效工件。"""
        statement = (
            select(AgentArtifact)
            .where(AgentArtifact.session_id == session_id, AgentArtifact.superseded_at.is_(None))
            .order_by(AgentArtifact.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_recent_active_artifacts_by_source(
        self,
        *,
        session_id: int,
        source_tools: list[str],
        limit: int,
    ) -> list[AgentArtifact]:
        """按来源工具读取会话内最近的未失效工件。"""
        if not source_tools or limit <= 0:
            return []
        statement = (
            select(AgentArtifact)
            .where(
                AgentArtifact.session_id == session_id,
                AgentArtifact.source_tool.in_(source_tools),
                AgentArtifact.superseded_at.is_(None),
            )
            .order_by(AgentArtifact.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def supersede_artifacts(self, *, session_id: int, source_tools: list[str]) -> list[int]:
        """把会话内指定来源工具的未失效工件标记为失效，返回受影响主键。"""
        if not source_tools:
            return []
        statement = select(AgentArtifact.id).where(
            AgentArtifact.session_id == session_id,
            AgentArtifact.source_tool.in_(source_tools),
            AgentArtifact.superseded_at.is_(None),
        )
        ids = [int(row) for row in self.session.scalars(statement)]
        if ids:
            self.session.execute(
                update(AgentArtifact)
                .where(AgentArtifact.id.in_(ids))
                .values(superseded_at=DateTimeUtil.now_utc())
            )
        return ids

    def save(self, instance: Any) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
