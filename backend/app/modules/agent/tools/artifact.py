"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手会话工件回读工具
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.tools.context import AgentToolContext


class ArtifactAgentTool:
    """会话工件回读工具。"""

    def __init__(self, context: AgentToolContext) -> None:
        self.context = context

    def read_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 artifact_id 回读工件片段。"""
        artifact_id = arguments.get("artifact_id")
        if artifact_id is None:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "缺少 artifact_id")
        artifact = self.context.agent_repository.get_active_artifact(self.context.session_id, int(artifact_id))
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
