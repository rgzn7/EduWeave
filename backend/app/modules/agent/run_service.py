"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手运行服务：事件写入、运行终态流转与事件序列化
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.agent.models import AgentRun, AgentRunEvent
from app.modules.agent.repository import AgentRepository
from app.shared.utils.datetime_util import DateTimeUtil

# 终态运行状态
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class AgentRunService:
    """运行事件与终态管理。"""

    def __init__(self, db: Session, repository: AgentRepository | None = None) -> None:
        self.db = db
        self.repository = repository or AgentRepository(db)

    def emit_event(
        self,
        run: AgentRun,
        *,
        event_type: str,
        title: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentRunEvent:
        """写入一条运行事件并提交，供 SSE 增量拉取。"""
        event = self.repository.add_event(
            run_id=run.id,
            session_id=run.session_id,
            event_type=event_type,
            title=title,
            message=message,
            payload_json=payload,
        )
        run.updated_at = DateTimeUtil.now_utc()
        self.db.add(run)
        self.db.commit()
        return event

    def mark_succeeded(self, run: AgentRun, final_text: str) -> AgentRun:
        """运行成功：落库助手消息并置成功态。"""
        now = DateTimeUtil.now_utc()
        assistant_message = self.repository.create_message(
            session_id=run.session_id,
            user_id=run.user_id,
            role="assistant",
            content=final_text,
            run_id=run.id,
        )
        run.status = "succeeded"
        run.assistant_message_id = assistant_message.id
        run.final_response = final_text
        run.locked_by = ""
        run.lease_expires_at = None
        run.completed_at = now
        run.updated_at = now
        self.db.add(run)
        self.repository.touch_session(run.session_id)
        self.db.commit()
        self.emit_event(
            run,
            event_type="succeeded",
            title="回答完成",
            message="Agent 已生成最终回答",
            payload={"assistant_message_id": assistant_message.id, "text": final_text},
        )
        return run

    def mark_failed(self, run: AgentRun, *, error_code: str, message: str) -> AgentRun:
        """运行失败：置失败态（不再重试时调用）。"""
        now = DateTimeUtil.now_utc()
        run.status = "failed"
        run.last_error_code = error_code
        run.error_message = message
        run.locked_by = ""
        run.lease_expires_at = None
        run.completed_at = now
        run.updated_at = now
        self.db.add(run)
        self.db.commit()
        self.emit_event(
            run,
            event_type="failed",
            title="运行失败",
            message=message,
            payload={"error_code": error_code},
        )
        return run

    def cancel_run(self, run: AgentRun) -> AgentRun:
        """取消运行。"""
        now = DateTimeUtil.now_utc()
        run.status = "cancelled"
        run.locked_by = ""
        run.lease_expires_at = None
        run.completed_at = now
        run.updated_at = now
        self.db.add(run)
        self.db.commit()
        self.emit_event(run, event_type="cancelled", title="已取消", message="运行已被用户取消")
        return run

    @staticmethod
    def to_event_response(event: AgentRunEvent) -> dict[str, Any]:
        """把运行事件序列化为响应字典。"""
        return {
            "id": event.id,
            "run_id": event.run_id,
            "seq": event.seq,
            "event_type": event.event_type,
            "title": event.title,
            "message": event.message,
            "payload": event.payload_json,
            "created_at": DateTimeUtil.to_isoformat(event.created_at) if event.created_at else None,
        }
