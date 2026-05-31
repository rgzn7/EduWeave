"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手运行执行器：组装上下文、驱动 LLM 工具循环、写入透明事件
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.memory import AgentArtifactMemoryService, AgentContextAssembler
from app.modules.agent.models import AgentRun
from app.modules.agent.repository import AgentRepository
from app.modules.agent.run_service import AgentRunService
from app.modules.agent.runtime.guard import AgentToolCallGuard
from app.modules.agent.runtime.llm_runner import AgentLLMRunner
from app.modules.agent.runtime.prompts import build_location_context_text, build_static_system_messages
from app.modules.agent.tools.registry import AgentToolRegistry
from app.modules.agent.tools.summary import summarize_arguments, summarize_result
from app.modules.auth.models import SysUser
from app.modules.curriculum.repository import CurriculumRepository


class AgentRunCancelled(Exception):
    """运行被用户取消的内部信号。"""


class AgentRunExecutor:
    """单个 Agent 运行的 LLM 工具循环执行器。"""

    def __init__(self, db: Session, current_user: SysUser, run: AgentRun) -> None:
        self.db = db
        self.current_user = current_user
        self.run = run
        self.settings = get_settings()
        self.repository = AgentRepository(db)
        self.run_service = AgentRunService(db, self.repository)
        self.context = run.context_json or {}
        self.tool_registry = AgentToolRegistry(db, current_user, session_id=run.session_id, context=self.context)
        self.tool_guard = AgentToolCallGuard(self.settings, self.tool_registry)
        self.llm_runner = AgentLLMRunner(self.settings)
        self.context_assembler = AgentContextAssembler(self.settings)
        self.context_pack = {}
        self.artifact_memory = AgentArtifactMemoryService(
            db=db,
            settings=self.settings,
            repository=self.repository,
            run=run,
            context_assembler=self.context_assembler,
            context_pack=self.context_pack,
        )
        self.query_terms: list[str] = []
        self.current_round = 0
        self.cache_biz_key = f"agent-{run.session_id}"

    def execute(self) -> str:
        """执行 LLM 工具循环，返回最终回答文本。"""
        history = self.repository.list_messages(self.run.session_id, limit=self.settings.agent_history_max_messages)
        if not history:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "会话消息为空")
        current_prompt = self._find_current_prompt(history)
        self.query_terms = self.context_assembler.extract_query_terms(current_prompt)
        self.artifact_memory.warm_start_context_pack(self.query_terms)

        static_messages = build_static_system_messages(self._build_location_context_text())
        conversation: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content or ""} for message in history
        ]
        tools = self.tool_registry.build_tools()
        final_retry = 0

        while True:
            self.current_round += 1
            self._assert_not_cancelled()
            if self.current_round > self.settings.agent_max_tool_rounds:
                self.tool_guard.trigger_final_round("已达到本次运行最大工具循环轮数")
            if self.current_round > self.settings.agent_max_tool_rounds + 3:
                return "（本次未能在限定轮数内生成回答，请补充说明后重试）"
            forced_final = self.tool_guard.tool_quota_exhausted_reason is not None
            tool_choice = "none" if forced_final else "auto"
            messages = [
                *static_messages,
                *self.artifact_memory.render_artifact_memory_messages(),
                *self.artifact_memory.render_context_pack_messages(),
                *conversation,
                *self.tool_guard.build_quota_notice_messages(forced_final),
            ]
            result = self.llm_runner.run_chat(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                cache_biz_key=self.cache_biz_key,
                cache_user_id=self.current_user.id,
            )

            if result.tool_calls and not forced_final:
                inline_text = (result.content or "").strip()
                if inline_text:
                    self.run_service.emit_event(
                        self.run,
                        event_type="assistant_thinking",
                        title="Agent 思考",
                        message="模型在调用工具前输出了一段说明",
                        payload={"text": inline_text},
                    )
                    conversation.append({"role": "assistant", "content": inline_text})
                for tool_call in result.tool_calls:
                    conversation.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("call_id") or "",
                            "name": tool_call.get("name") or "",
                            "arguments": tool_call.get("arguments") or "{}",
                        }
                    )
                    conversation.append(self._execute_tool_call(tool_call))
                continue

            text = (result.content or "").strip()
            if text:
                return text
            if forced_final or final_retry >= 2:
                return text or "（本次未能生成回答，请补充说明后重试）"
            final_retry += 1
            conversation.append({"role": "user", "content": "请基于以上信息直接给出最终回答。"})

    def _assert_not_cancelled(self) -> None:
        """每轮开始前检查运行是否被取消。"""
        status = self.db.scalar(select(AgentRun.status).where(AgentRun.id == self.run.id))
        if status == "cancelled":
            raise AgentRunCancelled()

    def _find_current_prompt(self, history: list) -> str:
        """读取本次运行触发的用户文本。"""
        for message in history:
            if message.id == self.run.user_message_id and message.role == "user":
                return message.content or ""
        for message in reversed(history):
            if message.role == "user":
                return message.content or ""
        return ""

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """执行单个工具调用并返回 function_call_output 项。"""
        tool_name = str(tool_call.get("name") or "")
        arguments = AgentLLMRunner.parse_tool_arguments(tool_call.get("arguments"))

        blocked = self.tool_guard.record_tool_call(tool_name, arguments)
        if blocked is not None:
            argument_summary = summarize_arguments(tool_name, arguments)
            self.run_service.emit_event(
                self.run,
                event_type="tool_call",
                title=f"工具调用被拒：{tool_name}",
                message=str(blocked.get("message") or "工具调用被守护规则拒绝"),
                payload={
                    "tool_name": tool_name,
                    "arguments": argument_summary,
                    "blocked_reason": blocked.get("error_code"),
                },
            )
            self.run_service.emit_event(
                self.run,
                event_type="tool_result",
                title=f"工具拒绝返回：{tool_name}",
                message=str(blocked.get("message") or "工具调用被守护规则拒绝"),
                payload={
                    "tool_name": tool_name,
                    "arguments": argument_summary,
                    "summary": str(blocked.get("message") or ""),
                    "ok": False,
                    "blocked_reason": blocked.get("error_code"),
                },
            )
            return {
                "type": "function_call_output",
                "call_id": str(tool_call.get("call_id") or ""),
                "output": json.dumps(blocked, ensure_ascii=False, default=str),
            }

        self.run_service.emit_event(
            self.run,
            event_type="tool_call",
            title=f"调用工具：{tool_name}",
            message="Agent 正在调用项目工具",
            payload={"tool_name": tool_name, "arguments": summarize_arguments(tool_name, arguments)},
        )
        result = self.tool_registry.execute_tool(tool_name, arguments)

        artifact = None
        if isinstance(result, dict) and result.get("ok") and tool_name in {"read_lesson_plan", "read_outline"}:
            artifact = self.artifact_memory.maybe_persist_resource(
                tool_name,
                arguments,
                result,
                query_terms=self.query_terms,
                round_index=self.current_round,
            )
        elif isinstance(result, dict) and result.get("ok") and tool_name == "search_textbook":
            artifact = self.artifact_memory.persist_search_textbook_index(
                arguments,
                result,
                round_index=self.current_round,
            )

        model_result = self._build_model_tool_result(tool_name, result)
        self.run_service.emit_event(
            self.run,
            event_type="tool_result",
            title=f"工具返回：{tool_name}",
            message="工具结果已返回给 Agent",
            payload={
                "tool_name": tool_name,
                "arguments": summarize_arguments(tool_name, arguments),
                "summary": summarize_result(tool_name, result),
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "artifact_id": artifact.id if artifact is not None else None,
            },
        )

        if isinstance(result, dict) and result.get("artifact_updated"):
            self._handle_write_supersede(tool_name, result)

        return {
            "type": "function_call_output",
            "call_id": str(tool_call.get("call_id") or ""),
            "output": json.dumps(model_result, ensure_ascii=False, default=str),
        }

    @staticmethod
    def _build_model_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """构造回灌给 LLM 的工具结果，控制 token 体积。"""
        if not isinstance(result, dict):
            return {"ok": False, "error": "invalid_result"}
        if tool_name == "search_textbook" and result.get("ok"):
            return {key: value for key, value in result.items() if key != "content"}
        return result

    def _handle_write_supersede(self, tool_name: str, result: dict[str, Any]) -> None:
        """写工具成功后，失效同源读工件并发出产物更新事件。"""
        self.run_service.emit_event(
            self.run,
            event_type="artifact_updated",
            title="资源已更新",
            message=str(result.get("message") or "资源已写入新版本"),
            payload={
                "tool_name": tool_name,
                "artifact": result.get("artifact"),
                "lesson_plan_id": result.get("lesson_plan_id"),
                "curriculum_plan_id": result.get("curriculum_plan_id"),
                "class_session_no": result.get("class_session_no"),
                "version_no": result.get("version_no"),
            },
        )
        self.artifact_memory.supersede_artifacts_for_write(tool_name)

    def _build_location_context_text(self) -> str | None:
        """从 run.context_json 解析所在位置上下文描述。"""
        curriculum_plan_id = self.context.get("curriculum_plan_id")
        class_session_no = self.context.get("class_session_no")
        project_id = self.context.get("project_id")
        curriculum_repository = CurriculumRepository(self.db)
        project_title: str | None = None
        curriculum_title: str | None = None
        lesson_title: str | None = None
        if curriculum_plan_id is None and class_session_no is None:
            if project_id is None:
                return None
            project = curriculum_repository.get_project(int(project_id))
            project_title = project.name if project is not None else None
            return build_location_context_text(
                project_title=project_title,
                project_id=int(project_id),
                curriculum_title=None,
                curriculum_plan_id=None,
                class_session_no=None,
                lesson_title=None,
            )
        if curriculum_plan_id is not None:
            curriculum_plan = curriculum_repository.get_curriculum_plan_for_owner(
                int(curriculum_plan_id), self.current_user.id
            )
            if curriculum_plan is not None:
                curriculum_title = curriculum_plan.plan_title
                project = curriculum_repository.get_project(curriculum_plan.project_id)
                project_title = project.name if project is not None else None
                if project_id is None:
                    project_id = curriculum_plan.project_id
                if class_session_no is not None:
                    from app.modules.p0_models import LessonPlan

                    lesson = self.db.scalar(
                        select(LessonPlan)
                        .where(
                            LessonPlan.curriculum_plan_id == int(curriculum_plan_id),
                            LessonPlan.class_session_no == int(class_session_no),
                            LessonPlan.version_status == "ready",
                        )
                        .order_by(LessonPlan.version_no.desc())
                        .limit(1)
                    )
                    lesson_title = lesson.lesson_title if lesson is not None else None
        return build_location_context_text(
            project_title=project_title,
            project_id=int(project_id) if project_id is not None else None,
            curriculum_title=curriculum_title,
            curriculum_plan_id=int(curriculum_plan_id) if curriculum_plan_id is not None else None,
            class_session_no=int(class_session_no) if class_session_no is not None else None,
            lesson_title=lesson_title,
        )
