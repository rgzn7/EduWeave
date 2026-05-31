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


class AgentRunCancelled(Exception):
    """运行被用户取消的内部信号。"""
from app.modules.agent.context_pack import AgentContextAssembler, ContextPackEntry
from app.modules.agent.llm_runner import AgentLLMRunner
from app.modules.agent.models import AgentRun
from app.modules.agent.prompts import build_location_context_text, build_static_system_messages
from app.modules.agent.repository import AgentRepository
from app.modules.agent.run_service import AgentRunService
from app.modules.agent.tools import WRITE_SUPERSEDE_RULES, AgentToolService
from app.modules.auth.models import SysUser
from app.modules.curriculum.repository import CurriculumRepository

# 需要落工件的大段读工具
ARTIFACT_TOOLS = frozenset({"read_lesson_plan", "read_outline"})
SEARCH_TEXTBOOK_INDEX_TOOL = "search_textbook_index"
RESOURCE_MEMORY_LIMIT = 5
TEXTBOOK_SEARCH_MEMORY_LIMIT = 3


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
        self.tool_service = AgentToolService(
            db, current_user, session_id=run.session_id, context=self.context
        )
        self.llm_runner = AgentLLMRunner(self.settings)
        self.context_assembler = AgentContextAssembler(self.settings)
        self.context_pack: dict[int, ContextPackEntry] = {}
        self.query_terms: list[str] = []
        self.current_round = 0
        self.tool_call_count = 0
        # 同 (工具名+参数) 调用计数，用于同参重复熔断
        self.tool_signature_counts: dict[str, int] = {}
        # 非空时表示已进入「禁止工具、必须出最终回答」的终结态；下一轮强制 tool_choice=none。
        self.tool_quota_exhausted_reason: str | None = None
        # 终结态收尾通知是否已注入，避免每轮重复追加 system 消息。
        self._quota_notice_emitted = False
        self.cache_biz_key = f"agent-{run.session_id}"

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #
    def execute(self) -> str:
        """执行 LLM 工具循环，返回最终回答文本。"""
        history = self.repository.list_messages(self.run.session_id, limit=self.settings.agent_history_max_messages)
        if not history:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "会话消息为空")
        current_prompt = self._find_current_prompt(history)
        self.query_terms = self.context_assembler.extract_query_terms(current_prompt)
        self._warm_start_context_pack()

        static_messages = build_static_system_messages(self._build_location_context_text())
        conversation: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content or ""} for message in history
        ]
        tools = self.tool_service.build_tools()
        final_retry = 0

        while True:
            self.current_round += 1
            self._assert_not_cancelled()
            # 软上限：轮次超限即进入终结态；硬上限再加 3 轮缓冲兜底防死循环。
            if self.current_round > self.settings.agent_max_tool_rounds:
                self._trigger_final_round("已达到本次运行最大工具循环轮数")
            if self.current_round > self.settings.agent_max_tool_rounds + 3:
                return "（本次未能在限定轮数内生成回答，请补充说明后重试）"
            forced_final = self.tool_quota_exhausted_reason is not None
            tool_choice = "none" if forced_final else "auto"
            messages = [
                *static_messages,
                *self._render_artifact_memory_messages(),
                *self._render_context_pack_messages(),
                *conversation,
                *self._build_quota_notice_messages(forced_final),
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
                    # 工具调用前的说明文字回灌为 assistant 消息，保持 Responses 会话连续性
                    conversation.append({"role": "assistant", "content": inline_text})
                for tool_call in result.tool_calls:
                    # 先回灌 function_call 项，再回灌对应的 function_call_output，二者 call_id 必须配对
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
            # 无文本且未强制收尾：补一次收尾提示，超限后兜底返回
            if forced_final or final_retry >= 2:
                return text or "（本次未能生成回答，请补充说明后重试）"
            final_retry += 1
            conversation.append({"role": "user", "content": "请基于以上信息直接给出最终回答。"})

    def _assert_not_cancelled(self) -> None:
        """每轮开始前检查运行是否被取消（依赖上一轮事件提交后的新事务快照）。"""
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

    # ------------------------------------------------------------------ #
    # 运行守护：终结态、配额熔断、收尾通知
    # ------------------------------------------------------------------ #
    def _trigger_final_round(self, reason: str) -> None:
        """标记本次运行进入「禁止工具、必须出最终回答」的终结态（仅首次生效）。"""
        if self.tool_quota_exhausted_reason is None:
            self.tool_quota_exhausted_reason = reason

    def _record_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """记录工具调用并执行配额/重复/前置依赖检查。

        返回 None 表示放行；返回 dict 表示拒绝，调用方应原样作为 tool_result 透传给 LLM。
        - tool_quota_exhausted：已处于终结态，后续所有工具一律拒（should_finalize=True）。
        - read_before_write_required：写前未读同目标，仅本次拒、不消耗配额（should_finalize=False）。
        - max_tool_calls_reached：总次数超限，触发终结态并拒（should_finalize=True）。
        - repeated_tool_call_blocked：同参累计超限，仅本次拒、不终结（should_finalize=False，可换参或收尾）。
        """
        if self.tool_quota_exhausted_reason is not None:
            return {
                "ok": False,
                "error_code": "tool_quota_exhausted",
                "should_finalize": True,
                "message": (
                    f"本次运行工具配额已用尽（{self.tool_quota_exhausted_reason}），"
                    "请立刻基于现有上下文给出对教师最有用的最终中文回答，不要再尝试调用任何工具。"
                ),
            }

        # read-before-write 硬约束：不消耗配额、不计入重复签名，避免合理 retry 被惩罚。
        precondition_block = self.tool_service.check_write_precondition(tool_name, arguments)
        if precondition_block is not None:
            return precondition_block

        next_total = self.tool_call_count + 1
        if next_total > self.settings.agent_max_tool_calls:
            self._trigger_final_round("已达到本次运行最大工具调用次数")
            return {
                "ok": False,
                "error_code": "max_tool_calls_reached",
                "should_finalize": True,
                "message": (
                    f"已累计调用工具 {self.tool_call_count} 次，达到本次运行上限 "
                    f"{self.settings.agent_max_tool_calls} 次。请立刻基于现有上下文给出最终中文回答，"
                    "不要再尝试调用任何工具。"
                ),
            }

        signature = json.dumps(
            {"tool_name": tool_name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        next_sig_count = self.tool_signature_counts.get(signature, 0) + 1
        if next_sig_count > self.settings.agent_repeated_tool_call_limit:
            # 仅本次同参调用被拒，不进入终结态；LLM 可换参继续，或直接给最终回答。
            return {
                "ok": False,
                "error_code": "repeated_tool_call_blocked",
                "should_finalize": False,
                "message": (
                    f"已对 {tool_name} 用完全相同的参数调用 "
                    f"{self.settings.agent_repeated_tool_call_limit} 次。请改用不同参数继续，"
                    "或直接基于现有上下文给出最终中文回答，不要再用相同参数重试。"
                ),
            }

        self.tool_call_count = next_total
        self.tool_signature_counts[signature] = next_sig_count
        return None

    def _build_quota_notice_messages(self, forced_final: bool) -> list[dict[str, Any]]:
        """终结态首轮注入一次性 system 收尾通知，告知 LLM 立即给出最终回答。"""
        if not forced_final or self.tool_quota_exhausted_reason is None or self._quota_notice_emitted:
            return []
        self._quota_notice_emitted = True
        return [
            {
                "role": "system",
                "content": (
                    f"[系统通知] 本次运行已进入收尾阶段（{self.tool_quota_exhausted_reason}），"
                    "工具调用已禁用。请立刻基于以上全部上下文，用简体中文 Markdown 给出对教师最有用的最终回答。"
                ),
            }
        ]

    # ------------------------------------------------------------------ #
    # 工具调用
    # ------------------------------------------------------------------ #
    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """执行单个工具调用并返回 function_call_output 项。"""
        tool_name = str(tool_call.get("name") or "")
        arguments = AgentLLMRunner.parse_tool_arguments(tool_call.get("arguments"))

        # 配额/重复/前置依赖守护：命中即拒绝，不执行真实工具、不落工件、不失效同源工件。
        blocked = self._record_tool_call(tool_name, arguments)
        if blocked is not None:
            argument_summary = AgentToolService.summarize_arguments(tool_name, arguments)
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
            payload={"tool_name": tool_name, "arguments": AgentToolService.summarize_arguments(tool_name, arguments)},
        )
        result = self.tool_service.execute_tool(tool_name, arguments)

        artifact = None
        if isinstance(result, dict) and result.get("ok") and tool_name in ARTIFACT_TOOLS:
            artifact = self._maybe_persist_artifact(tool_name, arguments, result)
        elif isinstance(result, dict) and result.get("ok") and tool_name == "search_textbook":
            artifact = self._persist_search_textbook_index(arguments, result)

        model_result = self._build_model_tool_result(tool_name, result)
        self.run_service.emit_event(
            self.run,
            event_type="tool_result",
            title=f"工具返回：{tool_name}",
            message="工具结果已返回给 Agent",
            payload={
                "tool_name": tool_name,
                "arguments": AgentToolService.summarize_arguments(tool_name, arguments),
                "summary": AgentToolService.summarize_result(tool_name, result),
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "artifact_id": artifact.id if artifact is not None else None,
            },
        )

        # 写工具成功后失效同源读工件
        if isinstance(result, dict) and result.get("artifact_updated"):
            self._handle_write_supersede(tool_name, result)

        return {
            "type": "function_call_output",
            "call_id": str(tool_call.get("call_id") or ""),
            "output": json.dumps(model_result, ensure_ascii=False, default=str),
        }

    def _maybe_persist_artifact(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]):
        """资源读结果落工件；仅大内容以描述符替换回灌内容，同步刷新 context pack。"""
        content = result.get("content")
        if not isinstance(content, str):
            return None
        title = AgentToolService.summarize_result(tool_name, result)
        preview = content[: self.settings.agent_artifact_preview_chars]
        artifact = self.repository.create_or_reuse_artifact(
            session_id=self.run.session_id,
            source_tool=tool_name,
            content_text=content,
            title=title,
            summary=preview,
        )
        self.db.commit()
        # 刷新运行上下文包
        if self.settings.agent_context_pack_enabled:
            entry = self.context_assembler.build_entry(
                artifact_id=artifact.id,
                source_tool=tool_name,
                source_arguments=arguments,
                title=title,
                content=content,
                query_terms=self.query_terms,
                round_index=self.current_round,
            )
            self.context_pack[artifact.id] = entry
            self._enforce_context_pack_capacity()
        result["artifact_id"] = artifact.id
        if len(content) >= self.settings.agent_artifact_inline_threshold:
            # 大内容用描述符替换；短内容保留内联结果，但同样提供 artifact_id 支持跨 run 指代。
            result["content"] = {
                "artifact_id": artifact.id,
                "total_chars": len(content),
                "preview": preview,
                "tool_hint": "完整内容已落入会话工件库，需要更长片段时调用 read_artifact(artifact_id, offset, length)",
            }
        return artifact

    def _persist_search_textbook_index(self, arguments: dict[str, Any], result: dict[str, Any]):
        """把教材检索命中关系持久化为轻量索引工件，不保存正文或命中窗口。"""
        query = str(result.get("query") or arguments.get("query") or "").strip()
        hits = []
        for hit in result.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            hits.append(
                {
                    "rank": hit.get("rank"),
                    "semantic_chunk_id": hit.get("semantic_chunk_id"),
                    "page_start": hit.get("page_start"),
                    "page_end": hit.get("page_end"),
                    "chapter_node_id": hit.get("chapter_node_id"),
                    "chapter_title": hit.get("chapter_title"),
                    "chunk_no": hit.get("chunk_no"),
                    "chunk_title": hit.get("chunk_title"),
                    "score": hit.get("score"),
                    "content_chars": hit.get("content_chars"),
                    "is_truncated": hit.get("is_truncated"),
                }
            )
        payload = {
            "run_id": self.run.id,
            "round_index": self.current_round,
            "query": query,
            "count": len(hits),
            "hits": hits,
        }
        content_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        title = f"教材检索：{query or '未命名查询'}（{len(hits)} 条）"
        artifact = self.repository.create_or_reuse_artifact(
            session_id=self.run.session_id,
            source_tool=SEARCH_TEXTBOOK_INDEX_TOOL,
            content_text=content_text,
            title=title,
            summary=content_text[: self.settings.agent_artifact_preview_chars],
        )
        self.db.commit()
        return artifact

    def _build_model_tool_result(self, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
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
        source_tools = WRITE_SUPERSEDE_RULES.get(tool_name)
        if not source_tools:
            return
        superseded_ids = self.repository.supersede_artifacts(
            session_id=self.run.session_id, source_tools=source_tools
        )
        self.db.commit()
        for artifact_id in superseded_ids:
            self.context_pack.pop(artifact_id, None)

    # ------------------------------------------------------------------ #
    # 上下文包
    # ------------------------------------------------------------------ #
    def _warm_start_context_pack(self) -> None:
        """跨运行预热：按当前问题在历史工件中检索关键命中段落。"""
        if not self.settings.agent_context_pack_enabled or not self.query_terms:
            return
        artifacts = self.repository.list_active_artifacts(self.run.session_id)
        for artifact in artifacts:
            if artifact.source_tool == SEARCH_TEXTBOOK_INDEX_TOOL:
                continue
            entry = self.context_assembler.build_warm_start_entry(
                artifact_id=artifact.id,
                source_tool=artifact.source_tool,
                source_arguments={},
                title=artifact.title or artifact.source_tool,
                content=artifact.content_text or "",
                query_terms=self.query_terms,
                round_index=0,
            )
            if entry is not None:
                self.context_pack[artifact.id] = entry
        self._enforce_context_pack_capacity()

    def _enforce_context_pack_capacity(self) -> None:
        """限制 context pack 条目数，淘汰最久未触达条目。"""
        max_entries = self.settings.agent_context_pack_max_entries
        if len(self.context_pack) <= max_entries:
            return
        ordered = sorted(
            self.context_pack.values(),
            key=lambda item: (item.last_touched_round, item.artifact_id),
        )
        for entry in ordered[: len(self.context_pack) - max_entries]:
            self.context_pack.pop(entry.artifact_id, None)

    def _render_context_pack_messages(self) -> list[dict[str, Any]]:
        """渲染运行上下文包为单条 system 消息。"""
        if not self.settings.agent_context_pack_enabled or not self.context_pack:
            return []
        text = self.context_assembler.render(
            list(self.context_pack.values()),
            budget_chars=self.settings.agent_context_pack_budget_chars,
        )
        if not text:
            return []
        return [{"role": "system", "content": text}]

    def _render_artifact_memory_messages(self) -> list[dict[str, Any]]:
        """渲染会话历史资源工件目录与教材检索索引，支持跨 run 指代。"""
        resource_artifacts = self.repository.list_recent_active_artifacts_by_source(
            session_id=self.run.session_id,
            source_tools=list(ARTIFACT_TOOLS),
            limit=RESOURCE_MEMORY_LIMIT,
        )
        search_indexes = self.repository.list_recent_active_artifacts_by_source(
            session_id=self.run.session_id,
            source_tools=[SEARCH_TEXTBOOK_INDEX_TOOL],
            limit=TEXTBOOK_SEARCH_MEMORY_LIMIT,
        )
        lines: list[str] = []
        if resource_artifacts:
            lines.append("[会话历史可回读资源]")
            lines.append("用户提到“刚才那个教案/大纲”时，优先参考这些 artifact_id；需要全文可调用 read_artifact。")
            for artifact in resource_artifacts:
                lines.append(
                    f"- artifact_id={artifact.id} | source_tool={artifact.source_tool} | "
                    f"title={artifact.title or artifact.source_tool} | total_chars={len(artifact.content_text or '')} | "
                    f"read_artifact({artifact.id}, offset, length)"
                )
        rendered_indexes = self._render_textbook_search_indexes(search_indexes)
        if rendered_indexes:
            if lines:
                lines.append("")
            lines.extend(rendered_indexes)
        if not lines:
            return []
        return [{"role": "system", "content": "\n".join(lines)}]

    def _render_textbook_search_indexes(self, search_indexes: list[Any]) -> list[str]:
        """渲染最近教材检索索引，保留 rank 到 semantic_chunk_id 的映射。"""
        if not search_indexes:
            return []
        lines = [
            "[最近教材检索索引]",
            "用户提到“刚才第 N 条/上次第 N 个结果”时，按最近一次检索的 rank 映射 semantic_chunk_id，"
            "再调用 read_textbook_chunk(semantic_chunk_id, offset, length) 回读正文。",
        ]
        for artifact in search_indexes:
            try:
                payload = json.loads(artifact.content_text or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            query = payload.get("query") or "未命名查询"
            hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
            lines.append(f"- search_index_artifact_id={artifact.id} | query={query} | count={len(hits)}")
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                title = hit.get("chunk_title") or hit.get("chapter_title") or "未命名片段"
                page_start = hit.get("page_start")
                page_end = hit.get("page_end")
                page_text = f"{page_start}-{page_end}" if page_start != page_end else str(page_start)
                lines.append(
                    f"  rank={hit.get('rank')} -> semantic_chunk_id={hit.get('semantic_chunk_id')} | "
                    f"pages={page_text} | title={title} | score={hit.get('score')} | "
                    f"is_truncated={hit.get('is_truncated')}"
                )
        return lines if len(lines) > 2 else []

    # ------------------------------------------------------------------ #
    # 所在位置上下文
    # ------------------------------------------------------------------ #
    def _build_location_context_text(self) -> str | None:
        """从 run.context_json 解析所在位置上下文描述（课次/大纲优先，单项目模式给项目级提示）。"""
        curriculum_plan_id = self.context.get("curriculum_plan_id")
        class_session_no = self.context.get("class_session_no")
        project_id = self.context.get("project_id")
        curriculum_repository = CurriculumRepository(self.db)
        project_title: str | None = None
        curriculum_title: str | None = None
        lesson_title: str | None = None
        # 单项目模式：无课次/大纲上下文，仅按 project_id 给项目名
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
                    from sqlalchemy import select

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
