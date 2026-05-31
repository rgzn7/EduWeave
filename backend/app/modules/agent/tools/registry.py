"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具注册、分发与写前读校验
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.tools.artifact import ArtifactAgentTool
from app.modules.agent.tools.constants import WRITE_SUPERSEDE_RULES
from app.modules.agent.tools.context import AgentToolContext
from app.modules.agent.tools.curriculum import CurriculumAgentTool
from app.modules.agent.tools.lesson import LessonAgentTool
from app.modules.agent.tools.schema import TOOL_SCHEMAS
from app.modules.agent.tools.summary import summarize_arguments, summarize_result
from app.modules.agent.tools.textbook import TextbookAgentTool
from app.modules.auth.models import SysUser


class AgentToolRegistry:
    """智能助手工具注册与执行入口。"""

    def __init__(
        self,
        db: Session | None = None,
        current_user: SysUser | None = None,
        *,
        session_id: int | None = None,
        context: dict[str, Any] | None = None,
        tool_context: AgentToolContext | None = None,
    ) -> None:
        if tool_context is None:
            if db is None or current_user is None or session_id is None:
                raise ValueError("缺少构造 AgentToolContext 所需参数")
            tool_context = AgentToolContext(db, current_user, session_id=session_id, context=context)
        self.context = tool_context
        self.curriculum_tool = CurriculumAgentTool(tool_context)
        self.lesson_tool = LessonAgentTool(tool_context)
        self.textbook_tool = TextbookAgentTool(tool_context)
        self.artifact_tool = ArtifactAgentTool(tool_context)
        self.handlers = {
            "list_curricula": self.curriculum_tool.list_curricula,
            "list_lessons": self.lesson_tool.list_lessons,
            "read_lesson_plan": self.lesson_tool.read_lesson_plan,
            "write_lesson_plan": self.lesson_tool.write_lesson_plan,
            "read_outline": self.curriculum_tool.read_outline,
            "write_outline": self.curriculum_tool.write_outline,
            "search_textbook": self.textbook_tool.search_textbook,
            "read_textbook_chunk": self.textbook_tool.read_textbook_chunk,
            "read_artifact": self.artifact_tool.read_artifact,
        }

    def build_tools(self) -> list[dict[str, Any]]:
        """返回 Chat Completions 工具定义。"""
        return TOOL_SCHEMAS

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """分发执行工具，统一异常转错误结果。"""
        handler = self.handlers.get(tool_name)
        if handler is None:
            return {
                "ok": False,
                "error": "unknown_tool",
                "error_code": "unknown_tool",
                "should_finalize": False,
                "message": f"未知工具：{tool_name}",
            }
        try:
            return handler(arguments)
        except AppException as exc:
            result: dict[str, Any] = {
                "ok": False,
                "error": exc.code.value,
                "error_code": exc.code.value,
                "should_finalize": False,
                "message": exc.message,
                "details": exc.details,
            }
            if exc.code == BusinessErrorCode.LLM_RESULT_INVALID and tool_name in WRITE_SUPERSEDE_RULES:
                result["llm_instruction"] = (
                    "content_json 未通过结构校验。请对照本工具参数中 content_json 的 JSON Schema 补齐全部必填字段后整体重写，"
                    "不要省略字段；可依据 details.errors 定位具体出错位置，再在已 read 的完整内容基础上修正。"
                )
            return result
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "tool_error",
                "error_code": "tool_error",
                "should_finalize": False,
                "message": str(exc),
            }

    def check_write_precondition(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """写工具的 read-before-write 硬约束。"""
        if tool_name == "write_lesson_plan":
            try:
                curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
                session_no = self.context.resolve_session_no(arguments)
            except AppException:
                return None
            if (curriculum_plan_id, session_no) in self.context.read_lesson_targets:
                return None
            try:
                existing = self.context.lesson_writer.get_lesson_plan_by_session(
                    curriculum_plan_id=curriculum_plan_id,
                    class_session_no=session_no,
                    owner_user_id=self.context.current_user.id,
                )
            except AppException:
                return None
            if existing is None:
                return None
            return {
                "ok": False,
                "error_code": "read_before_write_required",
                "should_finalize": False,
                "message": (
                    f"写入第 {session_no} 课次教案前，必须先在本次会话内调用 read_lesson_plan 取得该课次完整内容作为基线，"
                    "本次拒绝不消耗工具配额。"
                ),
                "llm_instruction": (
                    f"请先调用 read_lesson_plan(curriculum_plan_id={curriculum_plan_id}, class_session_no={session_no})，"
                    "在其完整 content_json 基础上做局部修改后整体写回，不要凭空构造教案结构。"
                ),
            }
        if tool_name == "write_outline":
            try:
                curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
            except AppException:
                return None
            if curriculum_plan_id in self.context.read_outline_targets:
                return None
            return {
                "ok": False,
                "error_code": "read_before_write_required",
                "should_finalize": False,
                "message": (
                    f"写入课程大纲（curriculum_plan_id={curriculum_plan_id}）前，必须先在本次会话内调用 read_outline 取得完整内容作为基线，"
                    "本次拒绝不消耗工具配额。"
                ),
                "llm_instruction": (
                    f"请先调用 read_outline(curriculum_plan_id={curriculum_plan_id})，"
                    "在其完整 content_json 基础上做局部修改后整体写回，不要凭空构造大纲结构。"
                ),
            }
        return None

    @staticmethod
    def summarize_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """压缩工具参数用于事件展示。"""
        return summarize_arguments(tool_name, arguments)

    @staticmethod
    def summarize_result(tool_name: str, result: dict[str, Any]) -> str:
        """生成工具结果的简短摘要。"""
        return summarize_result(tool_name, result)
