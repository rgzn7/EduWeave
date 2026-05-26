"""
@Date: 2026-05-22
@Author: xisy
@Discription: 任务恢复能力（失败重试与僵尸回收）测试
"""

from sqlalchemy import select, text

from app.core.constants import (
    ASSESSMENT_GENERATE_TASK_TYPE,
    COURSEWARE_GENERATE_TASK_TYPE,
    COVERAGE_ANALYZE_TASK_TYPE,
    CURRICULUM_GENERATE_TASK_TYPE,
    CURRICULUM_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    KNOWLEDGE_EXTRACT_TASK_TYPE,
    LESSON_PLAN_GENERATE_TASK_TYPE,
    PROFILE_EXTRACT_TASK_TYPE,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
    TEXTBOOK_PARSE_TASK_TYPE,
    TEXTBOOK_REPARSE_TASK_TYPE,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.auth.models import SysUser
from app.modules.p0_models import Project, TaskRecord, TaskStepRecord
from app.modules.task_center import recovery
from app.modules.task_center.recovery import (
    build_dispatch_payload,
    is_retryable_error,
    reap_stale_tasks_once,
    requeue_or_fail_task,
)
from app.modules.task_center.repository import TaskCenterRepository


def _create_processing_task(
    session,
    *,
    retry_count: int = 0,
    max_retry_count: int = 3,
    task_type: str = CURRICULUM_GENERATE_TASK_TYPE,
) -> TaskRecord:
    """构造一条处于 processing 状态、带步骤的任务记录。"""
    user = session.scalars(select(SysUser).where(SysUser.username == "teacher_demo")).first()
    project = Project(owner_user_id=user.id, name="恢复测试项目", subject_code="english", grade_code="grade_6")
    session.add(project)
    session.flush()
    task = TaskRecord(
        project_id=project.id,
        module_code=CURRICULUM_MODULE_CODE,
        task_type=task_type,
        task_status=TASK_STATUS_PROCESSING,
        queue_name=GENERATION_QUEUE_NAME,
        current_stage="invoke_llm_curriculum",
        progress_percent=40,
        retry_count=retry_count,
        max_retry_count=max_retry_count,
        payload_json={"generation_batch_id": 123, "curriculum_plan_id": 456},
        operator_user_id=user.id,
    )
    session.add(task)
    session.flush()
    for step_order, step_code in enumerate(["prepare_generation_baseline", "invoke_llm_curriculum"], start=1):
        session.add(
            TaskStepRecord(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_code,
                step_order=step_order,
                step_status=TASK_STATUS_PROCESSING,
            )
        )
    session.commit()
    return task


def test_is_retryable_error_classifies_by_code() -> None:
    """基础设施类错误与意外异常可重试，业务校验类错误不可重试。"""
    assert is_retryable_error(AppException(BusinessErrorCode.LLM_RESULT_INVALID, "x")) is True
    assert is_retryable_error(AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "x")) is True
    assert is_retryable_error(AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "x")) is False
    assert is_retryable_error(AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "x")) is False
    assert is_retryable_error(RuntimeError("x")) is True
    assert is_retryable_error(None) is True


def test_task_handler_registry_covers_all_task_types() -> None:
    """处理器注册表必须覆盖全部派发的任务类型，避免 reaper 无法重排。"""
    expected = {
        ASSESSMENT_GENERATE_TASK_TYPE,
        COURSEWARE_GENERATE_TASK_TYPE,
        COVERAGE_ANALYZE_TASK_TYPE,
        CURRICULUM_GENERATE_TASK_TYPE,
        KNOWLEDGE_EXTRACT_TASK_TYPE,
        LESSON_PLAN_GENERATE_TASK_TYPE,
        PROFILE_EXTRACT_TASK_TYPE,
        TEXTBOOK_PARSE_TASK_TYPE,
        TEXTBOOK_REPARSE_TASK_TYPE,
    }
    assert expected <= set(recovery.TASK_HANDLER_REGISTRY)


def test_requeue_or_fail_task_retries_retryable_error(seeded_session_factory, monkeypatch) -> None:
    """可重试错误且未超上限时应重排为 pending 并重新派发。"""
    calls: list = []
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: calls.append((a, k)))
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        repository = TaskCenterRepository(session)
        result = requeue_or_fail_task(
            repository,
            task,
            exc=AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 结果不合规"),
        )
        assert result is True
        session.refresh(task)
        assert task.task_status == TASK_STATUS_PENDING
        assert task.retry_count == 1
        assert task.current_stage is None
        assert task.worker_task_id is None
        assert len(calls) == 1
        steps = repository.list_task_steps(task.id)
        assert all(step.step_status == TASK_STATUS_PENDING for step in steps)
    finally:
        session.close()


def test_requeue_or_fail_task_fails_after_exhausting_retries(seeded_session_factory, monkeypatch) -> None:
    """重试次数耗尽后应判终态失败，不再重新派发。"""
    calls: list = []
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: calls.append(1))
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session, retry_count=3, max_retry_count=3)
        repository = TaskCenterRepository(session)
        result = requeue_or_fail_task(
            repository,
            task,
            exc=AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 结果不合规"),
        )
        assert result is False
        session.refresh(task)
        assert task.task_status == TASK_STATUS_FAILURE
        assert task.last_error_code == BusinessErrorCode.LLM_RESULT_INVALID.value
        assert task.finished_at is not None
        assert calls == []
    finally:
        session.close()


def test_requeue_or_fail_task_fails_non_retryable_error(seeded_session_factory, monkeypatch) -> None:
    """业务校验类错误应直接判终态失败，不消耗重试次数。"""
    calls: list = []
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: calls.append(1))
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        repository = TaskCenterRepository(session)
        result = requeue_or_fail_task(
            repository,
            task,
            exc=AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "基线不可用"),
        )
        assert result is False
        session.refresh(task)
        assert task.task_status == TASK_STATUS_FAILURE
        assert task.retry_count == 0
        assert calls == []
    finally:
        session.close()


def test_requeue_or_fail_task_fails_when_handler_unregistered(seeded_session_factory, monkeypatch) -> None:
    """任务类型未注册处理器时应判终态失败并给出专属错误码。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session, task_type="bogus_unregistered_type")
        repository = TaskCenterRepository(session)
        result = requeue_or_fail_task(
            repository,
            task,
            exc=AppException(BusinessErrorCode.LLM_RESULT_INVALID, "x"),
        )
        assert result is False
        session.refresh(task)
        assert task.task_status == TASK_STATUS_FAILURE
        assert task.last_error_code == "TASK_HANDLER_UNREGISTERED"
    finally:
        session.close()


def test_reap_stale_tasks_requeues_zombie(seeded_session_factory, monkeypatch) -> None:
    """超时的 processing 僵尸任务应被回收并重排。"""
    calls: list = []
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: calls.append(1))
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        session.execute(
            text("UPDATE task_record SET updated_at = NOW() - INTERVAL 7200 SECOND WHERE id = :task_id"),
            {"task_id": task.id},
        )
        session.commit()
        session.expire_all()
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["scanned"] == 1
        assert summary["requeued"] == 1
        session.refresh(task)
        assert task.task_status == TASK_STATUS_PENDING
        assert task.retry_count == 1
        assert len(calls) == 1
    finally:
        session.close()


def test_reap_stale_tasks_skips_fresh_task(seeded_session_factory, monkeypatch) -> None:
    """未超时的 processing 任务不应被回收。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        _create_processing_task(session)
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["scanned"] == 0
    finally:
        session.close()


def test_reap_stale_tasks_skips_external_wait_stage(seeded_session_factory, monkeypatch) -> None:
    """等待 Raccoon PPT 异步结果的停泊任务不应被 reaper 误判回收。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        session.execute(
            text(
                "UPDATE task_record SET current_stage = 'waiting_raccoon_result', "
                "updated_at = NOW() - INTERVAL 7200 SECOND WHERE id = :task_id"
            ),
            {"task_id": task.id},
        )
        session.commit()
        session.expire_all()
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["scanned"] == 0
        session.refresh(task)
        assert task.task_status == TASK_STATUS_PROCESSING
    finally:
        session.close()


def test_reap_stale_tasks_fails_exhausted_zombie(seeded_session_factory, monkeypatch) -> None:
    """重试耗尽的僵尸任务回收后应直接判终态失败。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session, retry_count=3, max_retry_count=3)
        session.execute(
            text("UPDATE task_record SET updated_at = NOW() - INTERVAL 7200 SECOND WHERE id = :task_id"),
            {"task_id": task.id},
        )
        session.commit()
        session.expire_all()
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["failed"] == 1
        session.refresh(task)
        assert task.task_status == TASK_STATUS_FAILURE
        assert task.last_error_code == "TASK_STALE_TIMEOUT"
    finally:
        session.close()


def test_build_dispatch_payload_includes_required_keys(seeded_session_factory) -> None:
    """重建派发 payload 时应补齐 task_record_id 与 operator_user_id。"""
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        payload = build_dispatch_payload(task)
        assert payload["task_record_id"] == task.id
        assert payload["operator_user_id"] == task.operator_user_id
        assert payload["curriculum_plan_id"] == 456
        assert "generation_batch_id" in payload
    finally:
        session.close()


def test_reap_stale_tasks_respects_recent_heartbeat(seeded_session_factory, monkeypatch) -> None:
    """即便 updated_at 老旧，只要 last_heartbeat_at 近期就不应被回收。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        # updated_at 远在过去，但心跳是近期 → 不算僵尸
        session.execute(
            text(
                "UPDATE task_record SET updated_at = NOW() - INTERVAL 7200 SECOND, "
                "last_heartbeat_at = NOW() - INTERVAL 60 SECOND WHERE id = :task_id"
            ),
            {"task_id": task.id},
        )
        session.commit()
        session.expire_all()
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["scanned"] == 0
        session.refresh(task)
        assert task.task_status == TASK_STATUS_PROCESSING
    finally:
        session.close()


def test_reap_stale_tasks_uses_stage_threshold_for_long_stages(seeded_session_factory, monkeypatch) -> None:
    """命中 STAGE_STALE_OVERRIDES 的阶段应按更宽阈值判定，不被默认阈值误判回收。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session, task_type=KNOWLEDGE_EXTRACT_TASK_TYPE)
        # 切到 invoke_llm_extract 长阶段（阈值 3600s）；心跳 2000s 前 → 默认 1800 阈值会回收，
        # 但 stage 阈值 3600 应跳过
        session.execute(
            text(
                "UPDATE task_record SET current_stage = 'invoke_llm_extract', "
                "updated_at = NOW() - INTERVAL 2000 SECOND, "
                "last_heartbeat_at = NOW() - INTERVAL 2000 SECOND WHERE id = :task_id"
            ),
            {"task_id": task.id},
        )
        session.commit()
        session.expire_all()
        summary = reap_stale_tasks_once(session, threshold_seconds=1800)
        assert summary["scanned"] == 1
        assert summary["requeued"] == 0
        assert summary["failed"] == 0
        assert summary["skipped_by_stage"] == 1
        session.refresh(task)
        assert task.task_status == TASK_STATUS_PROCESSING
    finally:
        session.close()


def test_requeue_rotates_execution_attempt_id(seeded_session_factory, monkeypatch) -> None:
    """重排重试时应轮换 execution_attempt_id，使旧 worker 的 CAS UPDATE 失效。"""
    monkeypatch.setattr(recovery, "dispatch_task", lambda *a, **k: None)
    session = seeded_session_factory()
    try:
        task = _create_processing_task(session)
        session.execute(
            text("UPDATE task_record SET execution_attempt_id = :attempt WHERE id = :task_id"),
            {"attempt": "old-attempt-id", "task_id": task.id},
        )
        session.commit()
        session.expire_all()

        task_repository = TaskCenterRepository(session)
        retried = requeue_or_fail_task(
            task_repository,
            task,
            error_code="EXTERNAL_SERVICE_ERROR",
            error_message="瞬时错误",
            force_retryable=True,
        )
        assert retried is True
        session.refresh(task)
        assert task.execution_attempt_id is not None
        assert task.execution_attempt_id != "old-attempt-id"
    finally:
        session.close()


def test_stale_attempt_error_is_not_retryable(seeded_session_factory) -> None:
    """StaleAttemptError 必须被判定为不可重试，避免循环触发重排。"""
    from app.modules.task_center.heartbeat import StaleAttemptError as _StaleAttemptError

    assert is_retryable_error(_StaleAttemptError(task_id=1, attempt_id="x")) is False
