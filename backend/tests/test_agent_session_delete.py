"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手会话删除接口测试：级联清理会话内部数据、运行中保护、归属隔离
"""

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessErrorCode
from app.core.security import hash_password
from app.modules.agent.models import AgentArtifact, AgentMessage, AgentRun, AgentRunEvent, AgentSession
from app.modules.agent.repository import AgentRepository
from app.modules.auth.models import SysUser
from app.modules.p0_models import Project
from app.shared.utils.datetime_util import DateTimeUtil
from test_project_api import build_auth_headers


def _get_demo_user(db: Session) -> SysUser:
    """读取测试默认教师。"""
    user = db.query(SysUser).filter(SysUser.username == "teacher_demo").one()
    return user


def _create_project(db: Session, owner_user_id: int, name: str = "助手删除项目") -> Project:
    """创建测试项目。"""
    project = Project(
        owner_user_id=owner_user_id,
        name=name,
        subject_code="english",
        grade_code="grade_6",
    )
    db.add(project)
    db.flush()
    return project


def _create_agent_session_bundle(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    run_status: str = "succeeded",
) -> dict[str, int]:
    """创建包含消息、运行、事件和工件的一组会话数据。"""
    now = DateTimeUtil.now_utc()
    agent_session = AgentSession(user_id=user_id, project_id=project_id, title="待删除会话")
    db.add(agent_session)
    db.flush()

    user_message = AgentMessage(
        session_id=agent_session.id,
        user_id=user_id,
        role="user",
        content="请帮我读取教案",
    )
    db.add(user_message)
    db.flush()

    run = AgentRun(
        session_id=agent_session.id,
        project_id=project_id,
        user_id=user_id,
        user_message_id=user_message.id,
        status=run_status,
        context_json={"project_id": project_id},
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        locked_by="",
        started_at=now if run_status != "pending" else None,
        completed_at=now if run_status in {"succeeded", "failed", "cancelled"} else None,
    )
    db.add(run)
    db.flush()

    assistant_message = AgentMessage(
        session_id=agent_session.id,
        user_id=user_id,
        role="assistant",
        content="已读取。",
        run_id=run.id,
    )
    db.add(assistant_message)
    db.flush()
    run.assistant_message_id = assistant_message.id
    db.add(run)

    event = AgentRunEvent(
        run_id=run.id,
        session_id=agent_session.id,
        seq=1,
        event_type="succeeded",
        title="回答完成",
        message="Agent 已生成最终回答",
        payload_json={"text": "已读取。"},
    )
    db.add(event)
    content_text = "完整教案内容"
    artifact = AgentArtifact(
        session_id=agent_session.id,
        source_tool="read_lesson_plan",
        content_hash=AgentRepository.compute_content_hash(content_text),
        title="第 1 课次教案",
        summary="完整教案",
        content_text=content_text,
    )
    db.add(artifact)
    db.commit()
    return {
        "session_id": agent_session.id,
        "run_id": run.id,
        "message_id": user_message.id,
        "assistant_message_id": assistant_message.id,
        "event_id": event.id,
        "artifact_id": artifact.id,
    }


def test_agent_session_delete_should_cleanup_internal_records(client, seeded_session_factory) -> None:
    """删除已完成会话时，应清理消息、运行、运行事件与会话工件。"""
    headers = build_auth_headers(client)
    db = seeded_session_factory()
    try:
        user = _get_demo_user(db)
        project = _create_project(db, user.id)
        ids = _create_agent_session_bundle(db, user_id=user.id, project_id=project.id)
    finally:
        db.close()

    response = client.delete(f"/api/v1/agent/sessions/{ids['session_id']}", headers=headers)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["session_id"] == ids["session_id"]
    assert payload["deleted_messages"] == 2
    assert payload["deleted_runs"] == 1
    assert payload["deleted_events"] == 1
    assert payload["deleted_artifacts"] == 1

    db = seeded_session_factory()
    try:
        assert db.get(AgentSession, ids["session_id"]) is None
        assert db.get(AgentMessage, ids["message_id"]) is None
        assert db.get(AgentMessage, ids["assistant_message_id"]) is None
        assert db.get(AgentRun, ids["run_id"]) is None
        assert db.get(AgentRunEvent, ids["event_id"]) is None
        assert db.get(AgentArtifact, ids["artifact_id"]) is None
    finally:
        db.close()


def test_agent_session_delete_should_reject_non_terminal_run(client, seeded_session_factory) -> None:
    """会话存在排队中或运行中的任务时，删除应返回冲突且不清理数据。"""
    headers = build_auth_headers(client)
    db = seeded_session_factory()
    try:
        user = _get_demo_user(db)
        project = _create_project(db, user.id)
        ids = _create_agent_session_bundle(db, user_id=user.id, project_id=project.id, run_status="pending")
    finally:
        db.close()

    response = client.delete(f"/api/v1/agent/sessions/{ids['session_id']}", headers=headers)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.TASK_CONFLICT.value

    db = seeded_session_factory()
    try:
        assert db.get(AgentSession, ids["session_id"]) is not None
        assert db.get(AgentMessage, ids["message_id"]) is not None
        assert db.get(AgentRun, ids["run_id"]) is not None
        assert db.get(AgentRunEvent, ids["event_id"]) is not None
        assert db.get(AgentArtifact, ids["artifact_id"]) is not None
    finally:
        db.close()


def test_agent_session_delete_should_hide_foreign_session(client, seeded_session_factory) -> None:
    """当前教师删除他人会话时，应按不存在处理且不清理对方数据。"""
    headers = build_auth_headers(client)
    db = seeded_session_factory()
    try:
        other_user = SysUser(
            username="teacher_other",
            display_name="其他教师",
            password_hash=hash_password("Teacher@123"),
            role_code="teacher",
            status="active",
        )
        db.add(other_user)
        db.flush()
        project = _create_project(db, other_user.id, name="其他教师项目")
        ids = _create_agent_session_bundle(db, user_id=other_user.id, project_id=project.id)
    finally:
        db.close()

    response = client.delete(f"/api/v1/agent/sessions/{ids['session_id']}", headers=headers)

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.TASK_NOT_FOUND.value

    db = seeded_session_factory()
    try:
        assert db.get(AgentSession, ids["session_id"]) is not None
        assert db.get(AgentMessage, ids["message_id"]) is not None
        assert db.get(AgentRun, ids["run_id"]) is not None
        assert db.get(AgentRunEvent, ids["event_id"]) is not None
        assert db.get(AgentArtifact, ids["artifact_id"]) is not None
    finally:
        db.close()
