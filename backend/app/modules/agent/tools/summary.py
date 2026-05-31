"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具参数与结果摘要
"""

from __future__ import annotations

from typing import Any


def summarize_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """压缩工具参数用于事件展示，content_json 等大字段只保留概要。"""
    _ = tool_name
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "content_json":
            summary[key] = {"_omitted": True, "keys": list(value.keys()) if isinstance(value, dict) else None}
        elif isinstance(value, str) and len(value) > 120:
            summary[key] = value[:120] + "…"
        else:
            summary[key] = value
    return summary


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
