"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手课程大纲工具
"""

from __future__ import annotations

import json
from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.tools.context import AgentToolContext


class CurriculumAgentTool:
    """课程大纲相关工具：大纲列表、读取与新版本写入。"""

    def __init__(self, context: AgentToolContext) -> None:
        self.context = context

    def list_curricula(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """列出本项目下全部课程大纲。"""
        _ = arguments
        if self.context.project_id is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "当前缺少项目上下文，无法列出课程大纲")
        plans = self.context.curriculum_repository.list_curriculum_plans_for_owner(
            self.context.current_user.id,
            project_id=int(self.context.project_id),
            knowledge_version_id=None,
            offset=0,
            limit=200,
        )
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
        return {"ok": True, "project_id": int(self.context.project_id), "count": len(items), "curricula": items}

    def read_outline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """读取指定大纲完整内容。"""
        curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
        curriculum_plan = self.context.curriculum_repository.get_curriculum_plan_for_owner(
            curriculum_plan_id, self.context.current_user.id
        )
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")
        self.context.read_outline_targets.add(curriculum_plan_id)
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

    def write_outline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """新建版本写入大纲。"""
        curriculum_plan_id = self.context.resolve_curriculum_plan_id(arguments)
        content_json = arguments.get("content_json")
        if not isinstance(content_json, dict):
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "content_json 必须为对象")
        new_plan = self.context.curriculum_writer.write_curriculum_version(
            curriculum_plan_id=curriculum_plan_id,
            content_json=content_json,
            owner_user_id=self.context.current_user.id,
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
