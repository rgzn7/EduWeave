"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具体系：教案读写、大纲读写、教材知识混合检索、工件回读
"""

from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.context_pack import AgentContextAssembler
from app.modules.agent.repository import AgentRepository
from app.modules.agent.writers import CurriculumWriteService, LessonPlanWriteService
from app.modules.auth.models import SysUser
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.schemas.base import BaseSchema
from app.shared.llm.service import OpenAICompatibleEmbeddingService
from app.shared.vector import MilvusVectorService

# 工具结果中需要落工件的「大字段」名
LARGE_RESULT_FIELD = "content"
# 工具结果落工件的来源工具集合（read 类）
ARTIFACT_SOURCE_TOOLS = frozenset({"read_lesson_plan", "read_outline"})
# 写工具触发失效的同源读工件来源
WRITE_SUPERSEDE_RULES: dict[str, list[str]] = {
    "write_lesson_plan": ["read_lesson_plan", "list_lessons"],
    "write_outline": ["read_outline"],
}
TEXTBOOK_SNIPPET_MAX_PASSAGES = 3
TEXTBOOK_READ_DEFAULT_LENGTH = 4000
TEXTBOOK_READ_MAX_LENGTH = 20000


def _inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """将 pydantic 生成的 $ref/$defs 内联展开为自包含嵌套结构（去除 $ref 与 $defs）。

    pydantic 的 $ref 形如 '#/$defs/X'（相对文档根）。本工具 schema 会被嵌入
    parameters.properties.content_json，'#/$defs/X' 相对请求根失配，导致 course_overview、
    teaching_flow、session_plans 等嵌套对象的结构丢失；上游网关对 $ref 支持也不稳。
    故在此解引用，使每个字段都带完整结构。教案/大纲 schema 无环，内联安全。
    """
    defs: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = resolve(copy.deepcopy(defs.get(ref.rsplit("/", 1)[-1], {})))
                # 合并 $ref 同级的其他键（如 description），$ref 本身丢弃
                siblings = {key: value for key, value in node.items() if key != "$ref"}
                if isinstance(target, dict):
                    target.update(siblings)
                return target
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve({key: value for key, value in schema.items() if key != "$defs"})


def _build_content_schema(model: type[BaseSchema], description: str) -> dict[str, Any]:
    """从 pydantic 结果模型派生 content_json 的 JSON Schema，直接注入工具定义。

    与服务端 model_validate 同源，模型据此即可在首轮产出结构正确的 content_json，
    无需靠校验报错试错；schema 随 pydantic 模型自动演进，避免手写结构与校验脱节。
    BaseSchema 无 alias，输出字段名为 snake_case，与库内存储及前端读取一致。
    先内联 $ref/$defs，避免嵌套对象结构在工具定义中丢失。
    """
    schema = _inline_json_schema_refs(model.model_json_schema())
    schema.pop("title", None)
    schema["description"] = description
    return schema


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_curricula",
            "description": (
                "列出本项目下全部课程大纲（大纲主键、标题、版本、课次数）。"
                "当不在具体课次教案上下文（如独立小助手单项目模式）、需要定位要操作哪个大纲时，先调用本工具，"
                "再把选定的 curriculum_plan_id 传给后续读写工具。"
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_lessons",
            "description": (
                "列出某课程大纲下全部课次（课次序号、标题、最新版本）。用于了解整体课次结构。"
                "不传 curriculum_plan_id 时默认当前所在大纲；单项目模式需显式传入 curriculum_plan_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "curriculum_plan_id": {"type": "integer", "description": "课程大纲主键；缺省为当前所在大纲"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lesson_plan",
            "description": (
                "读取某课次教案的完整结构化内容。不传 class_session_no 时默认读取当前所在课次教案；"
                "不传 curriculum_plan_id 时默认当前所在大纲，单项目模式需显式传入 curriculum_plan_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "curriculum_plan_id": {"type": "integer", "description": "课程大纲主键；缺省为当前所在大纲"},
                    "class_session_no": {"type": "integer", "description": "课次序号；缺省为当前所在课次"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_lesson_plan",
            "description": (
                "以「新建版本」方式写入某课次教案。必须传入完整的教案 content_json（与读取结构一致）；"
                "建议先 read_lesson_plan 取得完整内容，做局部修改后整体写回。不传 class_session_no 时写当前所在课次；"
                "不传 curriculum_plan_id 时默认当前所在大纲，单项目模式需显式传入 curriculum_plan_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "curriculum_plan_id": {"type": "integer", "description": "课程大纲主键；缺省为当前所在大纲"},
                    "class_session_no": {"type": "integer", "description": "课次序号；缺省为当前所在课次"},
                    "content_json": _build_content_schema(
                        LessonPlanGenerationResult,
                        "完整教案结构化内容，必须严格符合本 schema 的字段层级与必填项；"
                        "建议在 read_lesson_plan 取得的内容基础上做局部修改后整体回填，不要省略必填字段。",
                    ),
                    "edit_summary": {"type": "string", "description": "本次修改的简要说明"},
                },
                "required": ["content_json"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_outline",
            "description": (
                "读取某课程大纲的完整结构化内容（课程概览、课次安排等）。"
                "不传 curriculum_plan_id 时默认当前所在大纲，单项目模式需显式传入 curriculum_plan_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "curriculum_plan_id": {"type": "integer", "description": "课程大纲主键；缺省为当前所在大纲"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_outline",
            "description": (
                "以「新建版本」方式写入课程大纲。必须传入完整的大纲 content_json（与读取结构一致）；"
                "建议先 read_outline 取得完整内容，做局部修改后整体写回。"
                "不传 curriculum_plan_id 时默认当前所在大纲，单项目模式需显式传入 curriculum_plan_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "curriculum_plan_id": {"type": "integer", "description": "课程大纲主键；缺省为当前所在大纲"},
                    "content_json": _build_content_schema(
                        CurriculumGenerationResult,
                        "完整课程大纲结构化内容，必须严格符合本 schema 的字段层级与必填项；"
                        "建议在 read_outline 取得的内容基础上做局部修改后整体回填，不要省略必填字段。",
                    ),
                    "edit_summary": {"type": "string", "description": "本次修改的简要说明"},
                },
                "required": ["content_json"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_textbook",
            "description": (
                "在本项目教材语义块中做混合检索（BM25 + 稠密向量，RRF 重排），返回相关语义块索引与命中窗口。"
                "当命中窗口被截断、需要逐字引用或要据此修改资源时，继续调用 read_textbook_chunk 读取完整语义块。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题或关键词"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 6"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_textbook_chunk",
            "description": (
                "按 semantic_chunk_id 从 MySQL 回读教材语义块正文片段。"
                "用于 search_textbook 命中被截断、需要精确引用或需要完整教材依据时。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "semantic_chunk_id": {"type": "integer", "description": "教材语义块主键"},
                    "offset": {"type": "integer", "description": "起始字符偏移，默认 0"},
                    "length": {"type": "integer", "description": "读取长度，默认 4000，最大 20000"},
                },
                "required": ["semantic_chunk_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact",
            "description": "按 artifact_id 回读已落库工件的指定片段（offset/length），用于获取逐字精确内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "integer", "description": "工件主键"},
                    "offset": {"type": "integer", "description": "起始字符偏移，默认 0"},
                    "length": {"type": "integer", "description": "读取长度，默认 4000"},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        },
    },
]


class AgentToolService:
    """智能助手工具执行服务。"""

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
        # read-before-write 追踪：本次运行内已 read 过的写目标（解析默认值后的真实 id）。
        # 键为解析后的 (curriculum_plan_id, class_session_no) / curriculum_plan_id。
        self.read_lesson_targets: set[tuple[int, int]] = set()
        self.read_outline_targets: set[int] = set()
        # 加载所在大纲以补全 project_id 与 knowledge_version_id（用于教材检索范围）
        if self.curriculum_plan_id is not None:
            curriculum_plan = self.curriculum_repository.get_curriculum_plan_for_owner(
                int(self.curriculum_plan_id), current_user.id
            )
            if curriculum_plan is not None:
                self.project_id = curriculum_plan.project_id
                self.knowledge_version_id = curriculum_plan.knowledge_version_id

    def build_tools(self) -> list[dict[str, Any]]:
        """返回 Chat Completions 工具定义。"""
        return TOOL_SCHEMAS

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """分发执行工具，统一异常转错误结果。"""
        handlers = {
            "list_curricula": self._list_curricula,
            "list_lessons": self._list_lessons,
            "read_lesson_plan": self._read_lesson_plan,
            "write_lesson_plan": self._write_lesson_plan,
            "read_outline": self._read_outline,
            "write_outline": self._write_outline,
            "search_textbook": self._search_textbook,
            "read_textbook_chunk": self._read_textbook_chunk,
            "read_artifact": self._read_artifact,
        }
        handler = handlers.get(tool_name)
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
            # 业务校验类错误一律可恢复（模型可据 message 修正参数后重试），不强制收尾；
            # 同时保留 error 字段向后兼容，新增 error_code/should_finalize 供模型与执行器自纠偏。
            result: dict[str, Any] = {
                "ok": False,
                "error": exc.code.value,
                "error_code": exc.code.value,
                "should_finalize": False,
                "message": exc.message,
                "details": exc.details,
            }
            # 写工具结构校验失败时附自然语言纠偏指令，引导模型对照 schema 整体重写而非反复试错
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

    # ------------------------------------------------------------------ #
    # read-before-write 前置依赖校验
    # ------------------------------------------------------------------ #
    def check_write_precondition(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """写工具的 read-before-write 硬约束：写入前必须在本次运行内 read 过同一目标。

        命中拒绝时返回结构化拒绝 dict（由执行器透传给前端与 LLM，不消耗工具配额）；
        放行返回 None。目标 id 解析失败（如大纲不存在/越权）时返回 None，交由真实工具执行
        触发对应业务错误，避免在前置校验里吞掉错误语义。
        """
        if tool_name == "write_lesson_plan":
            try:
                curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
                session_no = self._resolve_session_no(arguments)
            except AppException:
                return None
            if (curriculum_plan_id, session_no) in self.read_lesson_targets:
                return None
            # 该课次尚无存量 ready 教案时属「首次新建」，无基线可读，直接放行；
            # 否则会与 read_lesson_plan 的 NOT_FOUND 形成死锁。归属异常时也放行交由真实工具报错。
            try:
                existing = self.lesson_writer.get_lesson_plan_by_session(
                    curriculum_plan_id=curriculum_plan_id,
                    class_session_no=session_no,
                    owner_user_id=self.current_user.id,
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
                curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
            except AppException:
                return None
            if curriculum_plan_id in self.read_outline_targets:
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

    # ------------------------------------------------------------------ #
    # 上下文解析
    # ------------------------------------------------------------------ #
    def _resolve_curriculum_plan_id(self, arguments: dict[str, Any]) -> int:
        """解析目标大纲：参数优先（带归属校验），其次当前所在大纲上下文。

        单项目模式无 context 大纲时，模型可通过 list_curricula 取得 curriculum_plan_id 显式传入。
        """
        value = arguments.get("curriculum_plan_id")
        if value is None:
            value = self.curriculum_plan_id
        if value is None:
            raise AppException(
                BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND,
                "未指定课程大纲，且当前不在任何课次/大纲上下文中。请先调用 list_curricula 选定大纲，再传入 curriculum_plan_id",
            )
        plan_id = int(value)
        # 参数传入的大纲需校验归属，防止跨用户越权访问
        if self.curriculum_plan_id is None or plan_id != int(self.curriculum_plan_id):
            if self.curriculum_repository.get_curriculum_plan_for_owner(plan_id, self.current_user.id) is None:
                raise AppException(
                    BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问"
                )
        return plan_id

    def _resolve_session_no(self, arguments: dict[str, Any]) -> int:
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

    def _require_positive_int_argument(self, arguments: dict[str, Any], key: str, label: str) -> int:
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

    def _resolve_read_window(self, arguments: dict[str, Any]) -> tuple[int, int]:
        """解析片段读取窗口参数。"""
        try:
            offset = int(arguments.get("offset") or 0)
            length = int(arguments.get("length") or TEXTBOOK_READ_DEFAULT_LENGTH)
        except (TypeError, ValueError) as exc:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "offset 与 length 必须为整数") from exc
        offset = max(0, offset)
        length = max(1, min(length, TEXTBOOK_READ_MAX_LENGTH))
        return offset, length

    def _ensure_textbook_context(self) -> tuple[int | None, int | None]:
        """校验当前运行具备教材范围，并返回项目/知识版本过滤条件。"""
        if self.knowledge_version_id is None and self.project_id is None:
            raise AppException(
                BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND,
                "当前缺少项目/知识版本上下文，无法读取教材",
            )
        project_id = int(self.project_id) if self.project_id is not None else None
        knowledge_version_id = int(self.knowledge_version_id) if self.knowledge_version_id is not None else None
        return project_id, knowledge_version_id

    def _build_textbook_snippets(self, content: str, query: str) -> list[dict[str, Any]]:
        """按检索词从教材正文中抽取 1-3 个自然边界窗口。"""
        normalized_content = content or ""
        if not normalized_content:
            return []
        assembler = AgentContextAssembler(self.settings)
        terms = assembler.extract_query_terms(query)
        snippets = assembler.find_key_passages(
            normalized_content,
            terms,
            max_passages=TEXTBOOK_SNIPPET_MAX_PASSAGES,
            passage_chars=self.settings.agent_context_pack_passage_chars,
        )
        if not snippets:
            head_len = min(len(normalized_content), self.settings.agent_context_pack_passage_chars)
            snippets = [{"offset": 0, "length": head_len, "text": normalized_content[:head_len], "score": 0.0}]
        return [
            {
                "offset": int(snippet["offset"]),
                "length": int(snippet["length"]),
                "text": str(snippet["text"]),
                "score": float(snippet.get("score") or 0.0),
            }
            for snippet in snippets
        ]

    @staticmethod
    def _is_textbook_hit_truncated(snippets: list[dict[str, Any]], total_chars: int) -> bool:
        """判断检索命中窗口是否只是正文的部分视图。"""
        return not (
            len(snippets) == 1
            and int(snippets[0].get("offset") or 0) == 0
            and int(snippets[0].get("length") or 0) >= total_chars
        )

    # ------------------------------------------------------------------ #
    # 教案
    # ------------------------------------------------------------------ #
    def _list_curricula(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """列出本项目下全部课程大纲，供模型在单项目模式下定位要操作的大纲。"""
        if self.project_id is None:
            raise AppException(
                BusinessErrorCode.PROJECT_NOT_FOUND,
                "当前缺少项目上下文，无法列出课程大纲",
            )
        plans = self.curriculum_repository.list_curriculum_plans_for_owner(
            self.current_user.id,
            project_id=int(self.project_id),
            knowledge_version_id=None,
            offset=0,
            limit=200,
        )
        # 同一大纲谱系按 version_no 倒序，取每个 project 下最新 ready 版本即可；此处返回全部 ready 供模型判断
        items = [
            {
                "curriculum_plan_id": plan.id,
                "plan_title": plan.plan_title,
                "version_no": plan.version_no,
                "course_count": plan.course_count,
                "version_status": plan.version_status,
            }
            for plan in plans
            if plan.version_status == "ready"
        ]
        return {"ok": True, "project_id": int(self.project_id), "count": len(items), "curricula": items}

    def _list_lessons(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """列出指定大纲下全部课次教案。"""
        curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
        lessons = self.lesson_repository.list_lesson_plans_for_owner(
            self.current_user.id,
            curriculum_plan_id=curriculum_plan_id,
            offset=0,
            limit=200,
        )
        latest_by_session: dict[int, Any] = {}
        for lesson in lessons:
            if lesson.version_status != "ready" or lesson.class_session_no is None:
                continue
            existing = latest_by_session.get(lesson.class_session_no)
            if existing is None or lesson.version_no > existing.version_no:
                latest_by_session[lesson.class_session_no] = lesson
        items = [
            {
                "class_session_no": lesson.class_session_no,
                "lesson_title": lesson.lesson_title,
                "version_no": lesson.version_no,
                "lesson_plan_id": lesson.id,
            }
            for lesson in sorted(latest_by_session.values(), key=lambda item: item.class_session_no)
        ]
        return {"ok": True, "curriculum_plan_id": curriculum_plan_id, "count": len(items), "lessons": items}

    def _read_lesson_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """读取某课次教案完整内容。"""
        curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
        session_no = self._resolve_session_no(arguments)
        lesson_plan = self.lesson_writer.get_lesson_plan_by_session(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=session_no,
            owner_user_id=self.current_user.id,
        )
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, f"第 {session_no} 课次暂无教案")
        # 记录已读目标，供 write_lesson_plan 的 read-before-write 前置校验放行
        self.read_lesson_targets.add((curriculum_plan_id, session_no))
        # summary_text/lesson_title 存于独立列、未落入生成期 content_json，
        # 这里以库内列为准回填，使读出的 content 与写入 schema（LessonPlanGenerationResult）同构，
        # 否则模型读到的 content 缺 summary_text，整体回写时会把它丢成 None（教案概述消失）。
        content = dict(lesson_plan.content_json or {})
        content["lesson_title"] = lesson_plan.lesson_title
        content["summary_text"] = lesson_plan.summary_text
        return {
            "ok": True,
            "lesson_plan_id": lesson_plan.id,
            "curriculum_plan_id": curriculum_plan_id,
            "class_session_no": lesson_plan.class_session_no,
            "version_no": lesson_plan.version_no,
            "lesson_title": lesson_plan.lesson_title,
            "content": json.dumps(content, ensure_ascii=False),
        }

    def _write_lesson_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """新建版本写入教案。"""
        curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
        session_no = self._resolve_session_no(arguments)
        content_json = arguments.get("content_json")
        if not isinstance(content_json, dict):
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "content_json 必须为对象")
        lesson_plan = self.lesson_writer.write_lesson_plan_version(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=session_no,
            content_json=content_json,
            owner_user_id=self.current_user.id,
        )
        return {
            "ok": True,
            "artifact_updated": True,
            "artifact": f"第 {session_no} 课次教案",
            "lesson_plan_id": lesson_plan.id,
            "curriculum_plan_id": curriculum_plan_id,
            "class_session_no": session_no,
            "version_no": lesson_plan.version_no,
            "edit_summary": arguments.get("edit_summary") or "Agent 修改教案",
            "message": f"已将第 {session_no} 课次教案写入为新版本 v{lesson_plan.version_no}",
        }

    # ------------------------------------------------------------------ #
    # 大纲
    # ------------------------------------------------------------------ #
    def _read_outline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """读取指定大纲完整内容。"""
        curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
        curriculum_plan = self.curriculum_repository.get_curriculum_plan_for_owner(
            curriculum_plan_id, self.current_user.id
        )
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")
        # 记录已读目标，供 write_outline 的 read-before-write 前置校验放行
        self.read_outline_targets.add(curriculum_plan_id)
        # summary_text/plan_title 存于独立列、未落入生成期 content_json，
        # 以库内列为准回填，保证读出 content 与写入 schema（CurriculumGenerationResult）同构，避免整体回写丢概述。
        content = dict(curriculum_plan.content_json or {})
        content["plan_title"] = curriculum_plan.plan_title
        content["summary_text"] = curriculum_plan.summary_text
        return {
            "ok": True,
            "curriculum_plan_id": curriculum_plan.id,
            "plan_title": curriculum_plan.plan_title,
            "version_no": curriculum_plan.version_no,
            "content": json.dumps(content, ensure_ascii=False),
        }

    def _write_outline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """新建版本写入大纲。"""
        curriculum_plan_id = self._resolve_curriculum_plan_id(arguments)
        content_json = arguments.get("content_json")
        if not isinstance(content_json, dict):
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "content_json 必须为对象")
        new_plan = self.curriculum_writer.write_curriculum_version(
            curriculum_plan_id=curriculum_plan_id,
            content_json=content_json,
            owner_user_id=self.current_user.id,
        )
        return {
            "ok": True,
            "artifact_updated": True,
            "artifact": "课程大纲",
            "curriculum_plan_id": new_plan.id,
            "parent_plan_id": curriculum_plan_id,
            "version_no": new_plan.version_no,
            "edit_summary": arguments.get("edit_summary") or "Agent 修改大纲",
            "message": f"已将课程大纲写入为新版本 v{new_plan.version_no}（新大纲主键 {new_plan.id}）",
        }

    # ------------------------------------------------------------------ #
    # 教材知识检索
    # ------------------------------------------------------------------ #
    def _search_textbook(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """教材语义块混合检索：Milvus 召回，MySQL 回源构造命中窗口。"""
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "检索问题不能为空")
        project_id, knowledge_version_id = self._ensure_textbook_context()
        top_k = int(arguments.get("top_k") or self.settings.agent_textbook_top_k)
        top_k = max(1, min(top_k, 20))

        if knowledge_version_id is not None:
            filter_expression = f"knowledge_version_id == {knowledge_version_id}"
        else:
            filter_expression = f"project_id == {project_id}"

        embedding_service = OpenAICompatibleEmbeddingService(settings=self.settings)
        query_vector = embedding_service.embed_texts([query])[0]
        vector_service = MilvusVectorService(settings=self.settings)
        vector_hits = vector_service.hybrid_search_vectors(
            "semantic_chunk_vector",
            query_vector=query_vector,
            query_text=query,
            limit=top_k,
            filter_expression=filter_expression,
        )

        hit_by_chunk_id: dict[int, Any] = {}
        ordered_chunk_ids: list[int] = []
        for hit in vector_hits:
            semantic_chunk_id = hit.semantic_chunk_id
            if semantic_chunk_id is None:
                continue
            chunk_id = int(semantic_chunk_id)
            if chunk_id in hit_by_chunk_id:
                continue
            hit_by_chunk_id[chunk_id] = hit
            ordered_chunk_ids.append(chunk_id)

        chunks = self.knowledge_repository.list_semantic_chunks_by_ids_for_owner(
            ordered_chunk_ids,
            self.current_user.id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        chunk_by_id = {int(chunk.id): chunk for chunk in chunks}
        chapter_ids = [
            int(chunk.chapter_node_id)
            for chunk in chunks
            if getattr(chunk, "chapter_node_id", None) is not None
        ]
        chapters = self.knowledge_repository.list_chapter_nodes_by_ids(chapter_ids)
        chapter_by_id = {int(chapter.id): chapter for chapter in chapters}

        hit_items: list[dict[str, Any]] = []
        for chunk_id in ordered_chunk_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                # Milvus 索引可能滞后于 MySQL 事实源，跳过不可回源命中。
                continue
            content = chunk.chunk_text or ""
            snippets = self._build_textbook_snippets(content, query)
            chapter = chapter_by_id.get(int(chunk.chapter_node_id)) if chunk.chapter_node_id is not None else None
            hit_items.append(
                {
                    "rank": len(hit_items) + 1,
                    "semantic_chunk_id": chunk.id,
                    "score": round(hit_by_chunk_id[chunk_id].score, 4),
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chapter_node_id": chunk.chapter_node_id,
                    "chapter_title": chapter.title if chapter is not None else None,
                    "chunk_no": chunk.chunk_no,
                    "chunk_title": chunk.chunk_title,
                    "content_chars": len(content),
                    "is_truncated": self._is_textbook_hit_truncated(snippets, len(content)),
                    "snippets": snippets,
                    "read_hint": (
                        "需要完整语义块时调用 "
                        f"read_textbook_chunk(semantic_chunk_id={chunk.id}, offset=0, length={TEXTBOOK_READ_DEFAULT_LENGTH})"
                    ),
                }
            )

        return {
            "ok": True,
            "query": query,
            "count": len(hit_items),
            "hits": hit_items,
        }

    def _read_textbook_chunk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 semantic_chunk_id 从 MySQL 回读教材语义块正文片段。"""
        semantic_chunk_id = self._require_positive_int_argument(arguments, "semantic_chunk_id", "semantic_chunk_id")
        project_id, knowledge_version_id = self._ensure_textbook_context()
        chunk = self.knowledge_repository.get_semantic_chunk_for_owner(
            semantic_chunk_id,
            self.current_user.id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        if chunk is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "教材语义块不存在或无权访问")

        content = chunk.chunk_text or ""
        if not content:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "教材语义块正文为空")
        offset, length = self._resolve_read_window(arguments)
        chunk_text = content[offset : offset + length]
        chapter = None
        if chunk.chapter_node_id is not None:
            chapters = self.knowledge_repository.list_chapter_nodes_by_ids([int(chunk.chapter_node_id)])
            chapter = chapters[0] if chapters else None
        return {
            "ok": True,
            "semantic_chunk_id": chunk.id,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chapter_node_id": chunk.chapter_node_id,
            "chapter_title": chapter.title if chapter is not None else None,
            "chunk_no": chunk.chunk_no,
            "chunk_title": chunk.chunk_title,
            "offset": offset,
            "returned_chars": len(chunk_text),
            "total_chars": len(content),
            "is_truncated": offset + length < len(content),
            "content": chunk_text,
        }

    # ------------------------------------------------------------------ #
    # 工件回读
    # ------------------------------------------------------------------ #
    def _read_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 artifact_id 回读工件片段。"""
        artifact_id = arguments.get("artifact_id")
        if artifact_id is None:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "缺少 artifact_id")
        artifact = self.agent_repository.get_active_artifact(self.session_id, int(artifact_id))
        if artifact is None:
            return {"ok": False, "error": "artifact_not_found", "message": "工件不存在或已失效"}
        offset = max(0, int(arguments.get("offset") or 0))
        length = int(arguments.get("length") or 4000)
        length = max(1, min(length, 20000))
        text = artifact.content_text or ""
        chunk = text[offset : offset + length]
        return {
            "ok": True,
            "artifact_id": artifact.id,
            "title": artifact.title,
            "offset": offset,
            "returned_chars": len(chunk),
            "total_chars": len(text),
            "is_truncated": offset + length < len(text),
            "content": chunk,
        }

    # ------------------------------------------------------------------ #
    # 摘要（事件展示用）
    # ------------------------------------------------------------------ #
    @staticmethod
    def summarize_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """压缩工具参数用于事件展示，content_json 等大字段只保留概要。"""
        summary: dict[str, Any] = {}
        for key, value in arguments.items():
            if key == "content_json":
                summary[key] = {"_omitted": True, "keys": list(value.keys()) if isinstance(value, dict) else None}
            elif isinstance(value, str) and len(value) > 120:
                summary[key] = value[:120] + "…"
            else:
                summary[key] = value
        return summary

    @staticmethod
    def summarize_result(tool_name: str, result: dict[str, Any]) -> str:
        """生成工具结果的简短摘要。"""
        if not isinstance(result, dict):
            return ""
        if not result.get("ok"):
            return f"失败：{result.get('message') or result.get('error')}"
        if tool_name == "search_textbook":
            return f"命中 {result.get('count', 0)} 条教材片段"
        if tool_name == "list_curricula":
            return f"共 {result.get('count', 0)} 个课程大纲"
        if tool_name == "list_lessons":
            return f"共 {result.get('count', 0)} 个课次"
        if tool_name in {"write_lesson_plan", "write_outline"}:
            return str(result.get("message") or "已写入")
        if tool_name == "read_lesson_plan":
            return f"第 {result.get('class_session_no')} 课次教案（v{result.get('version_no')}）"
        if tool_name == "read_outline":
            return f"大纲《{result.get('plan_title')}》（v{result.get('version_no')}）"
        if tool_name == "read_textbook_chunk":
            return f"读取教材语义块 {result.get('semantic_chunk_id')} 的 {result.get('returned_chars')} 字"
        if tool_name == "read_artifact":
            return f"读取工件 {result.get('artifact_id')} 的 {result.get('returned_chars')} 字"
        return "完成"
