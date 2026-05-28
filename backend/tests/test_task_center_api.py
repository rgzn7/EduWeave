"""
@Date: 2026-05-28
@Author: xisy
@Discription: 任务中心模块接口测试
"""

import pytest
from sqlalchemy import select

from app.core.constants import (
    GENERATION_QUEUE_NAME,
    LESSON_PLAN_GENERATE_TASK_TYPE,
    LESSON_PLAN_MODULE_CODE,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
)
from app.core.security import hash_password
from app.modules.auth.models import SysUser
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.tasks import _assert_generation_item_attempt
from app.modules.p0_models import Project, TaskRecord, TaskStepRecord
from app.modules.task_center.heartbeat import StaleAttemptError
from app.shared.queue.app import TaskDispatchResult


def build_auth_headers(client) -> dict[str, str]:
    """构造认证请求头。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def create_project(client, headers) -> int:
    """创建测试项目。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "任务项目", "subject_code": "english", "grade_code": "grade_6"},
    )
    return response.json()["data"]["id"]


def test_task_center_should_list_and_detail_tasks(client, stub_class_profile_llm) -> None:
    """任务中心应返回任务列表和详情。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files=[
            (
                "files",
                (
                    "student_profile.docx",
                    b"fake-docx-content",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
        data={"title": "三年级一班", "subject_scope": "english"},
    )

    list_response = client.get(f"/api/v1/tasks?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    payload = list_response.json()["data"]
    assert payload["pagination"]["total_count"] >= 1
    task_id = payload["items"][0]["id"]

    detail_response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["task_type"] == "learner_profile_extract"
    assert [step["step_code"] for step in detail_payload["steps"]] == [
        "prepare_source",
        "extract_local",
        "build_profile_version",
        "aggregate_class_profile",
    ]


def _seed_task_for_retry(session, *, task_status: str = TASK_STATUS_FAILURE, task_type: str = LESSON_PLAN_GENERATE_TASK_TYPE) -> int:
    """构造任务中心重试接口使用的任务。"""
    user = session.scalars(select(SysUser).where(SysUser.username == "teacher_demo")).first()
    project = Project(owner_user_id=user.id, name="重试任务项目", subject_code="math", grade_code="grade_3")
    session.add(project)
    session.flush()
    task = TaskRecord(
        project_id=project.id,
        module_code=LESSON_PLAN_MODULE_CODE,
        task_type=task_type,
        task_status=task_status,
        queue_name=GENERATION_QUEUE_NAME,
        current_stage="invoke_llm_lesson_plan",
        progress_percent=80,
        retry_count=3,
        max_retry_count=3,
        payload_json={"generation_batch_id": 1, "curriculum_plan_id": 2},
        last_error_code="LLM_REQUEST_FAILED",
        last_error_message="LLM 流式调用失败",
        operator_user_id=user.id,
        execution_attempt_id="old-attempt-id",
    )
    session.add(task)
    session.flush()
    session.add(
        TaskStepRecord(
            task_record_id=task.id,
            step_code="invoke_llm_lesson_plan",
            step_name="调用 LLM 生成教案",
            step_order=1,
            step_status=TASK_STATUS_FAILURE,
            progress_percent=80,
            detail_json={"failed_session_no": 3},
        )
    )
    session.commit()
    return task.id


def test_retry_failed_lesson_plan_task_should_requeue(
    client,
    seeded_session_factory,
    monkeypatch,
) -> None:
    """失败的教案生成任务应可手动重试并轮换 attempt。"""
    calls: list = []

    def fake_dispatch_task(*args, **kwargs):
        calls.append((args, kwargs))
        return TaskDispatchResult(worker_task_id="worker-retry-1", executed_inline=False)

    monkeypatch.setattr("app.shared.queue.dispatch_task", fake_dispatch_task)
    headers = build_auth_headers(client)
    session = seeded_session_factory()
    try:
        task_id = _seed_task_for_retry(session)
    finally:
        session.close()

    response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers)

    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["task_status"] == TASK_STATUS_PENDING
    assert payload["retry_count"] == 0
    assert payload["last_error_code"] is None
    assert calls and calls[0][0][0] == "app.modules.lesson_plan.tasks.run_generate_lesson_plan_task"

    session = seeded_session_factory()
    try:
        task = session.get(TaskRecord, task_id)
        assert task.execution_attempt_id is not None
        assert task.execution_attempt_id != "old-attempt-id"
        assert task.worker_task_id == "worker-retry-1"
        step = session.scalars(select(TaskStepRecord).where(TaskStepRecord.task_record_id == task_id)).one()
        assert step.step_status == TASK_STATUS_PENDING
        assert step.detail_json is None
    finally:
        session.close()


def test_retry_task_should_restore_failure_when_dispatch_failed(
    client,
    seeded_session_factory,
    monkeypatch,
) -> None:
    """手动重试派发失败时，任务应恢复失败态以便再次重试。"""

    def fake_dispatch_task(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("app.shared.queue.dispatch_task", fake_dispatch_task)
    headers = build_auth_headers(client)
    session = seeded_session_factory()
    try:
        task_id = _seed_task_for_retry(session)
    finally:
        session.close()

    response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers)

    assert response.status_code == 503
    session = seeded_session_factory()
    try:
        task = session.get(TaskRecord, task_id)
        assert task.task_status == TASK_STATUS_FAILURE
        assert task.last_error_code == "EXTERNAL_SERVICE_ERROR"
        assert task.execution_attempt_id != "old-attempt-id"
        step = session.scalars(select(TaskStepRecord).where(TaskStepRecord.task_record_id == task_id)).one()
        assert step.step_status == TASK_STATUS_FAILURE
        assert step.detail_json["error_code"] == "EXTERNAL_SERVICE_ERROR"
    finally:
        session.close()


def test_lesson_plan_generation_item_should_reject_stale_attempt(seeded_session_factory) -> None:
    """课次中间结果写入前应拒绝旧 attempt。"""
    session = seeded_session_factory()
    try:
        task_id = _seed_task_for_retry(session)
        task = session.get(TaskRecord, task_id)
        task.execution_attempt_id = "new-attempt-id"
        session.commit()

        with pytest.raises(StaleAttemptError):
            _assert_generation_item_attempt(LessonPlanRepository(session), task_id, "old-attempt-id")
    finally:
        session.close()


def test_retry_task_should_reject_non_failure_or_non_lesson_task(client, seeded_session_factory) -> None:
    """非失败任务或非教案生成任务不允许手动重试。"""
    headers = build_auth_headers(client)
    session = seeded_session_factory()
    try:
        processing_task_id = _seed_task_for_retry(session, task_status=TASK_STATUS_PROCESSING)
        other_task_id = _seed_task_for_retry(session, task_type="knowledge_extract")
    finally:
        session.close()

    processing_response = client.post(f"/api/v1/tasks/{processing_task_id}/retry", headers=headers)
    other_response = client.post(f"/api/v1/tasks/{other_task_id}/retry", headers=headers)

    assert processing_response.status_code == 409
    assert other_response.status_code == 409


def test_retry_task_should_reject_other_owner(client, seeded_session_factory, monkeypatch) -> None:
    """其他教师不能重试非自己项目的任务。"""
    monkeypatch.setattr(
        "app.shared.queue.dispatch_task",
        lambda *args, **kwargs: TaskDispatchResult(worker_task_id=None, executed_inline=False),
    )
    owner_headers = build_auth_headers(client)
    session = seeded_session_factory()
    try:
        task_id = _seed_task_for_retry(session)
        session.add(
            SysUser(
                username="teacher_retry_other",
                display_name="其他教师",
                password_hash=hash_password("Teacher@123"),
                role_code="teacher",
                status="active",
            )
        )
        session.commit()
    finally:
        session.close()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_retry_other", "password": "Teacher@123"},
    )
    other_headers = {"Authorization": f"Bearer {login_response.json()['data']['access_token']}"}

    assert client.post(f"/api/v1/tasks/{task_id}/retry", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/tasks/{task_id}/retry", headers=owner_headers).status_code == 202
