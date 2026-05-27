"""
@Date: 2026-05-26
@Author: xisy
@Discription: 任务心跳与执行实例（attempt）机制单测
"""

import time

from sqlalchemy import select, text

import pytest

from app.core.constants import CURRICULUM_GENERATE_TASK_TYPE, CURRICULUM_MODULE_CODE, GENERATION_QUEUE_NAME, TASK_STATUS_PROCESSING
from app.modules.auth.models import SysUser
from app.modules.p0_models import Project, TaskRecord, TaskStepRecord
from app.modules.task_center.heartbeat import (
    StaleAttemptError,
    TaskHeartbeat,
    TaskProgressPulse,
    ensure_attempt,
    start_attempt,
)
from app.modules.task_center.repository import TaskCenterRepository


def _create_task(session) -> TaskRecord:
    """构造一条 processing 状态的任务，用于心跳/抢占用例。"""
    user = session.scalars(select(SysUser).where(SysUser.username == "teacher_demo")).first()
    project = Project(owner_user_id=user.id, name="心跳测试项目", subject_code="english", grade_code="grade_6")
    session.add(project)
    session.flush()
    task = TaskRecord(
        project_id=project.id,
        module_code=CURRICULUM_MODULE_CODE,
        task_type=CURRICULUM_GENERATE_TASK_TYPE,
        task_status=TASK_STATUS_PROCESSING,
        queue_name=GENERATION_QUEUE_NAME,
        current_stage="invoke_llm_curriculum",
        progress_percent=30,
        payload_json={},
        operator_user_id=user.id,
    )
    session.add(task)
    session.commit()
    return task


def test_start_attempt_generates_and_persists_uuid(seeded_session_factory) -> None:
    """start_attempt 应生成 UUID 并写入 task_record.execution_attempt_id。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()
        session.refresh(task)
        assert task.execution_attempt_id == attempt_id
        assert len(attempt_id) == 36
    finally:
        session.close()


def test_heartbeat_tick_updates_progress_and_heartbeat(seeded_session_factory) -> None:
    """tick 应同时刷新心跳时间与业务字段。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        hb = TaskHeartbeat(session, task.id, attempt_id)
        hb.tick(progress_percent=45, current_stage="invoke_llm_curriculum")

        session.refresh(task)
        assert task.progress_percent == 45
        assert task.current_stage == "invoke_llm_curriculum"
        assert task.last_heartbeat_at is not None
    finally:
        session.close()


def test_heartbeat_tick_should_not_move_progress_backward(seeded_session_factory) -> None:
    """tick 写入较小任务进度时应保持原值，只允许继续前进。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        hb = TaskHeartbeat(session, task.id, attempt_id)
        hb.tick(progress_percent=20, current_stage="invoke_llm_curriculum")
        session.refresh(task)
        assert task.progress_percent == 30

        hb.tick(progress_percent=46, current_stage="invoke_llm_curriculum")
        session.refresh(task)
        assert task.progress_percent == 46
    finally:
        session.close()


def test_heartbeat_step_detail_should_not_move_progress_backward(seeded_session_factory) -> None:
    """update_step_detail 写入较小步骤进度时应保持原值。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        step = TaskStepRecord(
            task_record_id=task.id,
            step_code="invoke_llm_curriculum",
            step_name="调用 LLM 生成课程大纲",
            step_order=1,
            step_status=TASK_STATUS_PROCESSING,
            progress_percent=50,
        )
        session.add(step)
        session.commit()
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        hb = TaskHeartbeat(session, task.id, attempt_id)
        hb.update_step_detail(step_id=step.id, progress_percent=20, detail_json={"processed": 1})
        session.refresh(step)
        assert step.progress_percent == 50
        assert step.detail_json == {"processed": 1}

        hb.update_step_detail(step_id=step.id, progress_percent=80)
        session.refresh(step)
        assert step.progress_percent == 80
    finally:
        session.close()


def test_progress_pulse_should_advance_with_independent_session(seeded_session_factory) -> None:
    """TaskProgressPulse 应使用独立 Session 在阻塞期间推进进度。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        with TaskProgressPulse.from_session(
            session,
            task_id=task.id,
            attempt_id=attempt_id,
            current_stage="invoke_llm_curriculum",
            start_progress=30,
            max_progress=33,
            interval_seconds=0.05,
        ):
            time.sleep(0.12)

        session.refresh(task)
        assert 31 <= task.progress_percent <= 33
    finally:
        session.close()


def test_heartbeat_touch_only_updates_heartbeat(seeded_session_factory) -> None:
    """touch 只刷新心跳时间，不动业务字段。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        original_progress = task.progress_percent
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        hb = TaskHeartbeat(session, task.id, attempt_id)
        hb.touch()

        session.refresh(task)
        assert task.progress_percent == original_progress
        assert task.last_heartbeat_at is not None
    finally:
        session.close()


def test_heartbeat_tick_raises_on_stale_attempt(seeded_session_factory) -> None:
    """当 attempt_id 已被新 attempt 抢占，tick 必须抛 StaleAttemptError。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = start_attempt(repository, task.id)
        session.commit()

        # 模拟 reaper 轮换 attempt：CAS 应失败
        session.execute(
            text("UPDATE task_record SET execution_attempt_id = :new WHERE id = :task_id"),
            {"new": "new-attempt-id", "task_id": task.id},
        )
        session.commit()

        hb = TaskHeartbeat(session, task.id, attempt_id)
        with pytest.raises(StaleAttemptError):
            hb.tick(progress_percent=80)
    finally:
        session.close()


def test_ensure_attempt_creates_one_when_missing(seeded_session_factory) -> None:
    """payload 未带 attempt_id 时 ensure_attempt 应现场生成并提交。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        repository = TaskCenterRepository(session)
        attempt_id = ensure_attempt(repository, task.id, None)
        session.refresh(task)
        assert task.execution_attempt_id == attempt_id


    finally:
        session.close()


def test_ensure_attempt_passes_through_existing_value(seeded_session_factory) -> None:
    """payload 已带 attempt_id 时 ensure_attempt 直接返回，不动 DB。"""
    session = seeded_session_factory()
    try:
        task = _create_task(session)
        # 显式不写库；ensure_attempt 看到 attempt_id 入参即直接返回
        repository = TaskCenterRepository(session)
        attempt_id = ensure_attempt(repository, task.id, "preset-attempt")
        assert attempt_id == "preset-attempt"
        session.refresh(task)
        assert task.execution_attempt_id is None
    finally:
        session.close()
