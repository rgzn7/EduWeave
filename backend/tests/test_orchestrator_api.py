"""
@Date: 2026-05-26
@Author: xisy
@Discription: 一键生成编排 API 测试
"""

from sqlalchemy import select

from app.modules.auth.models import SysUser
from app.modules.p0_models import GenerationRun, Project


def _build_auth_headers(client) -> dict[str, str]:
    """登录获取 teacher_demo 的认证头。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _create_project(client, headers) -> int:
    """创建空项目，返回 project_id。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "编排测试项目", "subject_code": "math", "grade_code": "grade_3"},
    )
    return response.json()["data"]["id"]


def test_start_run_rejects_when_textbook_baseline_missing(client) -> None:
    """没有 current_textbook_version_id 时启动一键生成应明确 422。"""
    headers = _build_auth_headers(client)
    project_id = _create_project(client, headers)
    response = client.post(
        f"/api/v1/projects/{project_id}/generation-runs",
        headers=headers,
        json={"course_count": 2, "session_duration_minutes": 90},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["errors"][0]["code"] == "GENERATION_BASELINE_INVALID"


def test_start_run_returns_existing_active_run_idempotently(
    client,
    seeded_session_factory,
) -> None:
    """活跃 run 已存在时再次调用 start 不应新建，而是返回原 run（幂等）。"""
    headers = _build_auth_headers(client)
    project_id = _create_project(client, headers)

    # 直接在 DB 注入一个 running 的 run（绕过完整 fixture，专门验证幂等语义）
    session = seeded_session_factory()
    try:
        user = session.scalars(select(SysUser).where(SysUser.username == "teacher_demo")).first()
        run = GenerationRun(
            project_id=project_id,
            run_status="running",
            course_count=10,
            session_duration_minutes=40,
            auto_confirm_parse=1,
            created_by=user.id,
        )
        session.add(run)
        session.flush()
        project = session.get(Project, project_id)
        project.active_generation_run_id = run.id
        session.commit()
        run_id = run.id
    finally:
        session.close()

    # 第二次调 start：应直接返回已有 run（不抛 baseline 校验，因为 short-circuit 在锁后立刻命中）
    response = client.post(
        f"/api/v1/projects/{project_id}/generation-runs",
        headers=headers,
        json={"course_count": 5, "session_duration_minutes": 60},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["data"]["id"] == run_id
    assert body["data"]["course_count"] == 10  # 仍是旧 run 的参数，未被新参数覆盖

    # GET active 也能拿到同一 run
    active_response = client.get(
        f"/api/v1/projects/{project_id}/generation-runs/active",
        headers=headers,
    )
    assert active_response.status_code == 200
    assert active_response.json()["data"]["id"] == run_id


def test_get_active_run_returns_null_when_no_run(client) -> None:
    """无活跃 run 时 GET active 返回 null。"""
    headers = _build_auth_headers(client)
    project_id = _create_project(client, headers)
    response = client.get(
        f"/api/v1/projects/{project_id}/generation-runs/active",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_generation_process_reports_waiting_dispatch_when_run_waiting(
    client,
    seeded_session_factory,
) -> None:
    """active run 处于 running 但所有 step pending 时，generation-process 应给出 waiting_dispatch 细节。"""
    headers = _build_auth_headers(client)
    project_id = _create_project(client, headers)

    session = seeded_session_factory()
    try:
        user = session.scalars(select(SysUser).where(SysUser.username == "teacher_demo")).first()
        run = GenerationRun(
            project_id=project_id,
            run_status="running",
            course_count=10,
            session_duration_minutes=40,
            auto_confirm_parse=1,
            created_by=user.id,
        )
        session.add(run)
        session.flush()
        project = session.get(Project, project_id)
        project.active_generation_run_id = run.id
        session.commit()
    finally:
        session.close()

    response = client.get(
        f"/api/v1/projects/{project_id}/generation-process",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()["data"]
    # 整体仍 running，但细节指出在等待 dispatch
    assert body["status"] == "running"
    assert body["status_detail"] == "waiting_dispatch"
    # 6 步全 pending
    assert all(step["status"] == "pending" for step in body["steps"])
