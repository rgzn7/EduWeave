"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具定义与 content_json Schema 构建
"""

from __future__ import annotations

import copy
from typing import Any

from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.schemas.base import BaseSchema


def _inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """将 pydantic 生成的 $ref/$defs 内联展开为自包含嵌套结构。"""
    defs: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = resolve(copy.deepcopy(defs.get(ref.rsplit("/", 1)[-1], {})))
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
    """从 Pydantic 结果模型派生工具参数里的 content_json JSON Schema。"""
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
