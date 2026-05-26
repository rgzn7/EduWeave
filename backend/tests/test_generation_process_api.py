"""
@Date: 2026-05-26
@Author: xisy
@Discription: 生成过程展示接口测试
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import SysUser
from app.modules.p0_models import (
    CoverageReport,
    FileObject,
    GenerationBatch,
    KnowledgeVersion,
    LearnerProfileFile,
    LearnerProfileVersion,
    ParseVersion,
    Project,
    TaskRecord,
    TextbookVersion,
)


def build_auth_headers(client) -> dict[str, str]:
    """构造默认教师认证头。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def build_other_auth_headers(client, seeded_session_factory) -> dict[str, str]:
    """新建第二个教师并返回认证头。"""
    session = seeded_session_factory()
    try:
        session.add(
            SysUser(
                username="teacher_other",
                display_name="其他教师",
                password_hash=hash_password("Teacher@123"),
                role_code="teacher",
                status="active",
            )
        )
        session.commit()
    finally:
        session.close()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_other", "password": "Teacher@123"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def create_project_via_api(client, headers, *, name: str = "生成过程项目") -> int:
    """通过 API 创建一个空项目。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "subject_code": "math", "grade_code": "grade_3"},
    )
    return response.json()["data"]["id"]


def get_owner_user_id(session: Session, username: str = "teacher_demo") -> int:
    """读取测试教师主键。"""
    user = session.query(SysUser).filter(SysUser.username == username).one()
    return user.id


def _seed_file_object(session: Session, project_id: int, owner_user_id: int, biz_type: str) -> FileObject:
    """构造最小可用文件对象。"""
    file_object = FileObject(
        project_id=project_id,
        biz_type=biz_type,
        storage_provider="obs",
        bucket_name="test-bucket",
        object_key=f"projects/{project_id}/{biz_type}/{datetime.now(timezone.utc).timestamp()}.bin",
        original_filename="fake.bin",
        file_ext="bin",
        mime_type="application/octet-stream",
        file_size=1024,
        content_hash="fake-hash",
        source_type="user_upload",
        upload_status="uploaded",
        uploaded_by=owner_user_id,
    )
    session.add(file_object)
    session.flush()
    return file_object


def _seed_textbook_version(session: Session, project_id: int, owner_user_id: int) -> TextbookVersion:
    """构造教材版本及源文件。"""
    source_file = _seed_file_object(session, project_id, owner_user_id, "textbook_source")
    textbook_version = TextbookVersion(
        project_id=project_id,
        source_file_id=source_file.id,
        version_no=1,
        textbook_name="测试教材",
        subject_code="math",
        grade_code="grade_3",
        file_hash="fake-textbook-hash",
        page_count=12,
        parse_status="success",
        version_status="ready",
        uploaded_by=owner_user_id,
    )
    session.add(textbook_version)
    session.flush()
    return textbook_version


def _seed_parse_version(session: Session, project_id: int, textbook_version_id: int) -> ParseVersion:
    """构造解析版本。"""
    parse_version = ParseVersion(
        project_id=project_id,
        textbook_version_id=textbook_version_id,
        version_no=1,
        parse_mode="full",
        strategy_code="mineru_vlm_default",
        parse_status="success",
        review_status="confirmed",
        version_status="ready",
        page_count=12,
    )
    session.add(parse_version)
    session.flush()
    return parse_version


def _seed_knowledge_version(session: Session, project_id: int, parse_version_id: int, owner_user_id: int) -> KnowledgeVersion:
    """构造知识版本。"""
    knowledge_version = KnowledgeVersion(
        project_id=project_id,
        parse_version_id=parse_version_id,
        version_no=1,
        version_status="ready",
        summary_json={"chapter_count": 6, "point_count": 24},
        created_by=owner_user_id,
    )
    session.add(knowledge_version)
    session.flush()
    return knowledge_version


def _seed_learner_profile_version(session: Session, project_id: int, owner_user_id: int) -> LearnerProfileVersion:
    """构造学情文件与版本。"""
    profile_file_object = _seed_file_object(session, project_id, owner_user_id, "learner_profile_source")
    profile_file = LearnerProfileFile(
        project_id=project_id,
        source_file_id=profile_file_object.id,
        title="学生学情",
        file_status="uploaded",
        uploaded_by=owner_user_id,
    )
    session.add(profile_file)
    session.flush()
    profile_version = LearnerProfileVersion(
        project_id=project_id,
        profile_file_id=profile_file.id,
        version_no=1,
        subject_scope="math",
        extract_status="success",
        review_status="confirmed",
        version_status="ready",
        summary_text="测试学情摘要",
        created_by=owner_user_id,
    )
    session.add(profile_version)
    session.flush()
    return profile_version


def _seed_generation_batch(
    session: Session,
    project_id: int,
    knowledge_version_id: int,
    learner_profile_version_id: int,
    owner_user_id: int,
) -> GenerationBatch:
    """构造生成批次。"""
    batch = GenerationBatch(
        project_id=project_id,
        batch_no=1,
        batch_name="测试批次",
        trigger_mode="manual",
        batch_status="pending",
        knowledge_version_id=knowledge_version_id,
        learner_profile_version_id=learner_profile_version_id,
        course_count=2,
        session_duration_minutes=90,
        pipeline_options_json={"enabled_steps": ["curriculum", "lesson_plan", "coverage"]},
        created_by=owner_user_id,
    )
    session.add(batch)
    session.flush()
    return batch


def _seed_task(
    session: Session,
    *,
    project_id: int,
    module_code: str,
    task_type: str,
    biz_key: str,
    task_status: str,
    generation_batch_id: int | None = None,
    progress_percent: int = 100,
    result_json: dict[str, Any] | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    created_offset_seconds: int = 0,
) -> TaskRecord:
    """构造任务记录，created_offset_seconds 用于控制排序。"""
    base = datetime.now(timezone.utc) + timedelta(seconds=created_offset_seconds)
    terminal_statuses = {"success", "failure", "cancelled"}
    resolved_finished_at = finished_at
    if resolved_finished_at is None and task_status in terminal_statuses:
        resolved_finished_at = base + timedelta(seconds=60)
    task = TaskRecord(
        project_id=project_id,
        generation_batch_id=generation_batch_id,
        module_code=module_code,
        task_type=task_type,
        biz_key=biz_key,
        task_status=task_status,
        queue_name="test_queue",
        progress_percent=progress_percent,
        retry_count=0,
        max_retry_count=3,
        payload_json={"seeded": True},
        result_json=result_json,
        last_error_code=last_error_code,
        last_error_message=last_error_message,
        started_at=started_at or base,
        finished_at=resolved_finished_at,
    )
    session.add(task)
    session.flush()
    return task


@pytest.fixture()
def seeded_full_project(client, seeded_session_factory):
    """种入一个项目 + 教材/解析/知识/学情/批次基础数据，用于聚合接口测试。"""
    headers = build_auth_headers(client)
    project_id = create_project_via_api(client, headers)

    session = seeded_session_factory()
    try:
        owner_user_id = get_owner_user_id(session)
        project = session.get(Project, project_id)

        textbook_version = _seed_textbook_version(session, project_id, owner_user_id)
        parse_version = _seed_parse_version(session, project_id, textbook_version.id)
        knowledge_version = _seed_knowledge_version(session, project_id, parse_version.id, owner_user_id)
        profile_version = _seed_learner_profile_version(session, project_id, owner_user_id)
        batch = _seed_generation_batch(
            session,
            project_id,
            knowledge_version.id,
            profile_version.id,
            owner_user_id,
        )
        project.current_textbook_version_id = textbook_version.id
        project.current_learner_profile_version_id = profile_version.id
        project.latest_generation_batch_id = batch.id
        session.commit()

        return {
            "headers": headers,
            "project_id": project_id,
            "textbook_version_id": textbook_version.id,
            "parse_version_id": parse_version.id,
            "knowledge_version_id": knowledge_version.id,
            "profile_file_id": profile_version.profile_file_id,
            "profile_version_id": profile_version.id,
            "generation_batch_id": batch.id,
        }
    finally:
        session.close()


def test_generation_process_should_return_all_pending_for_empty_project(client) -> None:
    """空项目应返回 6 个 pending 步骤、整体 pending。"""
    headers = build_auth_headers(client)
    project_id = create_project_via_api(client, headers)

    response = client.get(f"/api/v1/projects/{project_id}/generation-process", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["project_id"] == project_id
    assert data["batch_id"] is None
    assert data["status"] == "pending"
    assert data["current_step_code"] is None
    assert [step["code"] for step in data["steps"]] == [
        "mineru_parse",
        "learner_profile",
        "knowledge_structure",
        "curriculum_plan",
        "lesson_plan_generate",
        "coverage_check",
    ]
    for step in data["steps"]:
        assert step["status"] == "pending"
        assert step["progress_percent"] == 0
        assert step["summary"] is None
        assert step["started_at"] is None
        assert step["finished_at"] is None
        assert step["error_message"] is None
    # 确认对外不暴露内部字段
    forbidden_keys = {"task_id", "worker_task_id", "queue_name", "module_code", "detail_json", "step_code"}
    for step in data["steps"]:
        assert forbidden_keys.isdisjoint(step.keys())
    # MinerU 名字必须出现，且不出现内部能力名
    display_names = [step["display_name"] for step in data["steps"]]
    assert any("MinerU" in name for name in display_names)
    descriptions = [step["description"] for step in data["steps"]]
    forbidden_tokens = ["LLM", "Milvus", "Celery", "Redis", "向量"]
    for token in forbidden_tokens:
        assert all(token not in name for name in display_names)
        assert all(token not in desc for desc in descriptions)


def test_generation_process_should_aggregate_pre_batch_progress(
    client, seeded_session_factory, seeded_full_project
) -> None:
    """完成前 3 个步骤后，后 3 步保持 pending，整体为 running。"""
    headers = seeded_full_project["headers"]
    project_id = seeded_full_project["project_id"]
    textbook_version_id = seeded_full_project["textbook_version_id"]
    parse_version_id = seeded_full_project["parse_version_id"]
    profile_file_id = seeded_full_project["profile_file_id"]

    session = seeded_session_factory()
    try:
        _seed_task(
            session,
            project_id=project_id,
            module_code="parsing",
            task_type="textbook_parse",
            biz_key=f"textbook_version:{textbook_version_id}:full",
            task_status="success",
            result_json={"parse_version_id": parse_version_id, "page_count": 12, "issue_count": 0},
            created_offset_seconds=-300,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="learner_profile",
            task_type="learner_profile_extract",
            biz_key=f"profile_file:{profile_file_id}:extract",
            task_status="success",
            result_json={"record_count": 5},
            created_offset_seconds=-240,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="knowledge",
            task_type="knowledge_extract",
            biz_key=f"parse_version:{parse_version_id}:knowledge",
            task_status="success",
            result_json={"chapter_count": 6, "point_count": 24},
            created_offset_seconds=-180,
        )
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/v1/projects/{project_id}/generation-process", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["batch_id"] == seeded_full_project["generation_batch_id"]
    assert data["status"] == "running"
    assert data["current_step_code"] == "curriculum_plan"
    by_code = {step["code"]: step for step in data["steps"]}
    assert by_code["mineru_parse"]["status"] == "succeeded"
    assert by_code["mineru_parse"]["summary"] == "已识别 12 页教材内容。"
    assert by_code["mineru_parse"]["progress_percent"] == 100
    assert by_code["mineru_parse"]["finished_at"] is not None
    assert by_code["learner_profile"]["status"] == "succeeded"
    assert by_code["learner_profile"]["summary"] == "已分析 5 份学情记录。"
    assert by_code["knowledge_structure"]["status"] == "succeeded"
    assert by_code["knowledge_structure"]["summary"] == "已识别 6 个章节、24 个知识点。"
    for code in ("curriculum_plan", "lesson_plan_generate", "coverage_check"):
        assert by_code[code]["status"] == "pending"
        assert by_code[code]["summary"] is None
        assert by_code[code]["error_message"] is None


def test_generation_process_should_report_succeeded_when_all_tasks_done(
    client, seeded_session_factory, seeded_full_project
) -> None:
    """6 个任务全部成功时整体 succeeded、不指明 current_step。"""
    headers = seeded_full_project["headers"]
    project_id = seeded_full_project["project_id"]
    textbook_version_id = seeded_full_project["textbook_version_id"]
    parse_version_id = seeded_full_project["parse_version_id"]
    profile_file_id = seeded_full_project["profile_file_id"]
    batch_id = seeded_full_project["generation_batch_id"]

    session = seeded_session_factory()
    try:
        _seed_task(
            session,
            project_id=project_id,
            module_code="parsing",
            task_type="textbook_parse",
            biz_key=f"textbook_version:{textbook_version_id}:full",
            task_status="success",
            result_json={"page_count": 18},
            created_offset_seconds=-600,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="learner_profile",
            task_type="learner_profile_extract",
            biz_key=f"profile_file:{profile_file_id}:extract",
            task_status="success",
            result_json={"record_count": 3},
            created_offset_seconds=-540,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="knowledge",
            task_type="knowledge_extract",
            biz_key=f"parse_version:{parse_version_id}:knowledge",
            task_status="success",
            result_json={"chapter_count": 4, "point_count": 12},
            created_offset_seconds=-480,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="curriculum",
            task_type="curriculum_generate",
            biz_key=f"generation_batch:{batch_id}:curriculum",
            task_status="success",
            generation_batch_id=batch_id,
            result_json={"curriculum_plan_id": 1},
            created_offset_seconds=-360,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="lesson_plan",
            task_type="lesson_plan_generate",
            biz_key=f"generation_batch:{batch_id}:lesson_plan",
            task_status="success",
            generation_batch_id=batch_id,
            result_json={"lesson_plan_count": 2, "lesson_plan_ids": [1, 2]},
            created_offset_seconds=-240,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="coverage",
            task_type="coverage_analyze",
            biz_key=f"generation_batch:{batch_id}:coverage",
            task_status="success",
            generation_batch_id=batch_id,
            result_json={"coverage_rate": 98.18, "warning_count": 1},
            created_offset_seconds=-120,
        )
        session.add(
            CoverageReport(
                generation_batch_id=batch_id,
                report_status="success",
                coverage_rate=98.18,
                warning_count=1,
                coverage_summary_json={},
                report_json={},
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/v1/projects/{project_id}/generation-process", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["current_step_code"] is None
    by_code = {step["code"]: step for step in data["steps"]}
    assert all(by_code[code]["status"] == "succeeded" for code in by_code)
    assert by_code["lesson_plan_generate"]["summary"] == "已生成 2 课时教案。"
    assert by_code["coverage_check"]["summary"] == "知识点覆盖 98.18%。"
    assert by_code["curriculum_plan"]["summary"] == "课程总纲已生成。"


def test_generation_process_should_map_internal_error_code_to_user_message(
    client, seeded_session_factory, seeded_full_project
) -> None:
    """失败任务的内部错误码应被映射成面向用户的中文文案。"""
    headers = seeded_full_project["headers"]
    project_id = seeded_full_project["project_id"]
    textbook_version_id = seeded_full_project["textbook_version_id"]
    parse_version_id = seeded_full_project["parse_version_id"]

    session = seeded_session_factory()
    try:
        _seed_task(
            session,
            project_id=project_id,
            module_code="parsing",
            task_type="textbook_parse",
            biz_key=f"textbook_version:{textbook_version_id}:full",
            task_status="success",
            result_json={"page_count": 12},
            created_offset_seconds=-200,
        )
        _seed_task(
            session,
            project_id=project_id,
            module_code="knowledge",
            task_type="knowledge_extract",
            biz_key=f"parse_version:{parse_version_id}:knowledge",
            task_status="failure",
            progress_percent=40,
            last_error_code="LLM_REQUEST_FAILED",
            last_error_message="LLM 调用栈泄漏：Traceback (most recent call last)...",
            created_offset_seconds=-150,
        )
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/v1/projects/{project_id}/generation-process", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["current_step_code"] == "knowledge_structure"
    by_code = {step["code"]: step for step in data["steps"]}
    knowledge_step = by_code["knowledge_structure"]
    assert knowledge_step["status"] == "failed"
    assert knowledge_step["error_message"] == "AI 工具暂时不可用，请稍后重试。"
    # 绝不能泄漏内部 traceback / last_error_message
    assert "Traceback" not in knowledge_step["error_message"]
    assert "LLM" not in knowledge_step["error_message"] or knowledge_step["error_message"].startswith("AI")


def test_generation_process_should_reject_other_owner_project(
    client, seeded_session_factory
) -> None:
    """其他教师无法看到非自己项目的生成过程。"""
    owner_headers = build_auth_headers(client)
    project_id = create_project_via_api(client, owner_headers)

    other_headers = build_other_auth_headers(client, seeded_session_factory)

    response = client.get(f"/api/v1/projects/{project_id}/generation-process", headers=other_headers)
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "PROJECT_NOT_FOUND"


def test_generation_process_should_require_authentication(client) -> None:
    """未登录访问应返回 401。"""
    response = client.get("/api/v1/projects/1/generation-process")
    assert response.status_code == 401
