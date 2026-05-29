"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手会话服务：创建会话、提交消息并入队运行
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.models import AgentRun, AgentSession
from app.modules.agent.repository import AgentRepository
from app.modules.auth.models import SysUser
from app.modules.p0_models import Project

# 所在课次教案上下文允许的字段
_CONTEXT_KEYS = ("project_id", "curriculum_plan_id", "class_session_no", "lesson_plan_id")


class AgentSessionService:
    """会话与运行入队服务。"""

    def __init__(self, db: Session, repository: AgentRepository | None = None) -> None:
        self.db = db
        self.repository = repository or AgentRepository(db)
        self.settings = get_settings()

    def _ensure_project_owned(self, project_id: int, user_id: int) -> None:
        """校验项目归属当前教师。"""
        project = self.db.scalar(
            select(Project).where(Project.id == project_id, Project.owner_user_id == user_id)
        )
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在或无权访问")

    def create_session(self, *, user: SysUser, project_id: int, title: str | None) -> AgentSession:
        """创建会话（强制绑定项目）。"""
        self._ensure_project_owned(project_id, user.id)
        session = self.repository.create_session(user_id=user.id, project_id=project_id, title=title)
        self.db.commit()
        return session

    def list_sessions(self, *, user: SysUser, project_id: int | None, page: int, page_size: int) -> list[AgentSession]:
        """分页查询会话。"""
        offset = (page - 1) * page_size
        return self.repository.list_sessions_for_owner(
            user.id, project_id=project_id, offset=offset, limit=page_size
        )

    def get_session(self, *, user: SysUser, session_id: int) -> AgentSession:
        """读取会话（含归属校验）。"""
        session = self.repository.get_session_for_owner(session_id, user.id)
        if session is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "会话不存在或无权访问")
        return session

    @staticmethod
    def _normalize_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
        """归一化所在课次教案上下文，仅保留约定字段。"""
        if not context:
            return None
        normalized = {key: context.get(key) for key in _CONTEXT_KEYS if context.get(key) is not None}
        return normalized or None

    def submit_run(
        self,
        *,
        user: SysUser,
        session_id: int,
        content: str,
        context: dict[str, Any] | None,
    ) -> AgentRun:
        """提交用户消息并创建待执行运行。"""
        normalized_content = (content or "").strip()
        if not normalized_content:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "消息内容不能为空")
        session = self.get_session(user=user, session_id=session_id)
        normalized_context = self._normalize_context(context)

        # 会话创建时已强制绑定项目；context.project_id 仅作显式覆盖，仍需校验归属
        project_id = session.project_id
        if normalized_context is not None and normalized_context.get("project_id") is not None:
            project_id = int(normalized_context["project_id"])
        if project_id is not None:
            self._ensure_project_owned(project_id, user.id)

        message = self.repository.create_message(
            session_id=session_id,
            user_id=user.id,
            role="user",
            content=normalized_content,
            metadata_json={"context": normalized_context} if normalized_context else None,
        )
        run = self.repository.create_run(
            session_id=session_id,
            project_id=project_id,
            user_id=user.id,
            user_message_id=message.id,
            context_json=normalized_context,
            max_attempts=3,
        )
        self.repository.touch_session(session_id)
        self.db.commit()
        return run
