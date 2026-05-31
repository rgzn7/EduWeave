"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具运行上下文
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.repository import AgentRepository
from app.modules.agent.writing import CurriculumWriteService, LessonPlanWriteService
from app.modules.auth.models import SysUser
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.agent.tools.constants import TEXTBOOK_READ_DEFAULT_LENGTH, TEXTBOOK_READ_MAX_LENGTH


class AgentToolContext:
    """集中保存工具执行所需的用户、会话、仓储、默认目标与运行内状态。"""

    def __init__(
        self,
        db: Session,
        current_user: SysUser,
        *,
        session_id: int,
        context: dict[str, Any] | None,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.session_id = session_id
        self.settings = get_settings()
        self.context = context or {}
        self.agent_repository = AgentRepository(db)
        self.lesson_repository = LessonPlanRepository(db)
        self.curriculum_repository = CurriculumRepository(db)
        self.knowledge_repository = KnowledgeRepository(db)
        self.lesson_writer = LessonPlanWriteService(db, self.lesson_repository)
        self.curriculum_writer = CurriculumWriteService(db, self.curriculum_repository)

        self.curriculum_plan_id = self.context.get("curriculum_plan_id")
        self.default_session_no = self.context.get("class_session_no")
        self.lesson_plan_id = self.context.get("lesson_plan_id")
        self.project_id = self.context.get("project_id")
        self.knowledge_version_id: int | None = None
        self.read_lesson_targets: set[tuple[int, int]] = set()
        self.read_outline_targets: set[int] = set()

        if self.curriculum_plan_id is not None:
            curriculum_plan = self.curriculum_repository.get_curriculum_plan_for_owner(
                int(self.curriculum_plan_id), current_user.id
            )
            if curriculum_plan is not None:
                self.project_id = curriculum_plan.project_id
                self.knowledge_version_id = curriculum_plan.knowledge_version_id

    def resolve_curriculum_plan_id(self, arguments: dict[str, Any]) -> int:
        """解析目标大纲：参数优先，其次当前所在大纲上下文。"""
        value = arguments.get("curriculum_plan_id")
        if value is None:
            value = self.curriculum_plan_id
        if value is None:
            raise AppException(
                BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND,
                "未指定课程大纲，且当前不在任何课次/大纲上下文中。请先调用 list_curricula 选定大纲，再传入 curriculum_plan_id",
            )
        plan_id = int(value)
        if self.curriculum_plan_id is None or plan_id != int(self.curriculum_plan_id):
            if self.curriculum_repository.get_curriculum_plan_for_owner(plan_id, self.current_user.id) is None:
                raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")
        return plan_id

    def resolve_session_no(self, arguments: dict[str, Any]) -> int:
        """解析目标课次：参数优先，其次当前所在课次。"""
        value = arguments.get("class_session_no")
        if value is None:
            value = self.default_session_no
        if value is None:
            raise AppException(
                BusinessErrorCode.LESSON_PLAN_NOT_FOUND,
                "未指定课次，且当前不在任何课次教案上下文，请提供 class_session_no",
            )
        return int(value)

    def require_positive_int_argument(self, arguments: dict[str, Any], key: str, label: str) -> int:
        """读取必填正整数工具参数。"""
        value = arguments.get(key)
        if value is None:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, f"缺少 {label}")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, f"{label} 必须为正整数") from exc
        if parsed <= 0:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, f"{label} 必须为正整数")
        return parsed

    def resolve_read_window(self, arguments: dict[str, Any]) -> tuple[int, int]:
        """解析片段读取窗口参数。"""
        try:
            offset = int(arguments.get("offset") or 0)
            length = int(arguments.get("length") or TEXTBOOK_READ_DEFAULT_LENGTH)
        except (TypeError, ValueError) as exc:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "offset 与 length 必须为整数") from exc
        offset = max(0, offset)
        length = max(1, min(length, TEXTBOOK_READ_MAX_LENGTH))
        return offset, length

    def ensure_textbook_context(self) -> tuple[int | None, int | None]:
        """校验当前运行具备教材范围，并返回项目/知识版本过滤条件。"""
        if self.knowledge_version_id is None and self.project_id is None:
            raise AppException(
                BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND,
                "当前缺少项目/知识版本上下文，无法读取教材",
            )
        project_id = int(self.project_id) if self.project_id is not None else None
        knowledge_version_id = int(self.knowledge_version_id) if self.knowledge_version_id is not None else None
        return project_id, knowledge_version_id
