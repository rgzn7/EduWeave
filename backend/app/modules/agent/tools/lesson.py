"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手教案工具
"""

from __future__ import annotations

import json
from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.tools.context import AgentToolContext


class LessonAgentTool:
    """教案相关工具：课次列表、教案读取与新版本写入。"""

    def __init__(self, context: AgentToolContext) -> None:
        self.context = context

    def list_lessons(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """列出指定大纲下全部课次教案。"""
        curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
        lessons = self.context.lesson_repository.list_lesson_plans_for_owner(
            self.context.current_user.id,
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

    def read_lesson_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """读取某课次教案完整内容。"""
        curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
        session_no = self.context.resolve_session_no(arguments)
        lesson_plan = self.context.lesson_writer.get_lesson_plan_by_session(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=session_no,
            owner_user_id=self.context.current_user.id,
        )
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, f"第 {session_no} 课次暂无教案")
        self.context.read_lesson_targets.add((curriculum_plan_id, session_no))
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

    def write_lesson_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """新建版本写入教案。"""
        curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
        session_no = self.context.resolve_session_no(arguments)
        content_json = arguments.get("content_json")
        if not isinstance(content_json, dict):
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "content_json 必须为对象")
        lesson_plan = self.context.lesson_writer.write_lesson_plan_version(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=session_no,
            content_json=content_json,
            owner_user_id=self.context.current_user.id,
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
