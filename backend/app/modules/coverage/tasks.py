"""
@Date: 2026-05-03
@Author: xisy
@Discription: 覆盖率分析模块任务执行能力
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import TASK_STATUS_FAILURE, TASK_STATUS_PROCESSING, TASK_STATUS_SUCCESS
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.coverage.repository import CoverageRepository
from app.modules.coverage.service import CoverageService
from app.modules.task_center.recovery import requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.utils import DateTimeUtil


def run_analyze_coverage_task(payload: dict) -> dict[str, int | float]:
    """执行覆盖率分析任务。"""
    session = _create_session(payload)
    repository = CoverageRepository(session)
    task_repository = TaskCenterRepository(session)
    service = CoverageService(session, repository)
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "覆盖率分析任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")

        generation_batch.batch_status = TASK_STATUS_PROCESSING
        generation_batch.started_at = generation_batch.started_at or now
        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_coverage_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_coverage_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        repository.save(generation_batch)
        task_repository.save(task)
        task_repository.save(step_map["prepare_coverage_baseline"])
        session.commit()

        _mark_step(
            step_map["prepare_coverage_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "generation_batch_id": generation_batch.id,
                "knowledge_version_id": generation_batch.knowledge_version_id,
                "curriculum_plan_id": generation_batch.curriculum_plan_id,
                "lesson_plan_count": len(repository.list_lesson_plans_by_batch(generation_batch.id)),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["collect_artifact_refs"], TASK_STATUS_PROCESSING, 35, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="collect_artifact_refs", progress_percent=35)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        coverage_payload = service.build_coverage_payload(generation_batch.id)
        _mark_step(
            step_map["collect_artifact_refs"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "coverage_rate": coverage_payload["coverage_rate"],
                "warning_count": coverage_payload["warning_count"],
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_coverage_report"], TASK_STATUS_PROCESSING, 65, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_coverage_report", progress_percent=65)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        report = service.create_coverage_report(generation_batch.id, coverage_payload)
        _mark_step(
            step_map["persist_coverage_report"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"coverage_report_id": report.id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["write_generation_trace"], TASK_STATUS_PROCESSING, 80, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="write_generation_trace", progress_percent=80)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        service.write_generation_traces(report, coverage_payload["trace_metadata"])
        _mark_step(
            step_map["write_generation_trace"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"trace_count": len(coverage_payload["trace_metadata"])},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["finalize_generation_batch"], TASK_STATUS_PROCESSING, 95, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_generation_batch", progress_percent=95)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        finished_at = DateTimeUtil.now_utc()
        generation_batch.batch_status = TASK_STATUS_SUCCESS
        generation_batch.finished_at = finished_at
        _mark_step(
            step_map["finalize_generation_batch"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"batch_status": TASK_STATUS_SUCCESS},
            finished_at=finished_at,
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="finalize_generation_batch",
            progress_percent=100,
            result_json={
                "generation_batch_id": generation_batch.id,
                "coverage_report_id": report.id,
                "coverage_rate": coverage_payload["coverage_rate"],
                "warning_count": coverage_payload["warning_count"],
            },
            finished_at=finished_at,
        )
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        return {
            "generation_batch_id": generation_batch.id,
            "coverage_report_id": report.id,
            "coverage_rate": coverage_payload["coverage_rate"],
            "warning_count": coverage_payload["warning_count"],
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _get_step_map(task_repository: TaskCenterRepository, task_record_id: int) -> dict[str, object]:
    return {
        step_code: task_repository.get_task_step(task_record_id, step_code)
        for step_code in (
            "prepare_coverage_baseline",
            "collect_artifact_refs",
            "persist_coverage_report",
            "write_generation_trace",
            "finalize_generation_batch",
        )
    }


def _mark_task(
    task,
    *,
    task_status: str,
    current_stage: str,
    progress_percent: int,
    started_at=None,
    finished_at=None,
    result_json: dict | None = None,
) -> None:
    task.task_status = task_status
    task.current_stage = current_stage
    task.progress_percent = progress_percent
    if started_at is not None:
        task.started_at = task.started_at or started_at
    if finished_at is not None:
        task.finished_at = finished_at
    if result_json is not None:
        task.result_json = result_json


def _mark_step(
    step,
    step_status: str,
    progress_percent: int,
    *,
    detail_json: dict | None = None,
    started_at=None,
    finished_at=None,
) -> None:
    step.step_status = step_status
    step.progress_percent = progress_percent
    if detail_json is not None:
        step.detail_json = detail_json
    if started_at is not None:
        step.started_at = step.started_at or started_at
    if finished_at is not None:
        step.finished_at = finished_at


def _mark_task_failure(
    task_repository: TaskCenterRepository,
    repository: CoverageRepository,
    payload: dict,
    exc: Exception,
) -> None:
    """处理覆盖率分析任务失败：可重试错误重排重试，终态失败时级联标记生成批次。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    terminal_failed = not requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.COVERAGE_TASK_FAILED,
    )
    if terminal_failed:
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is not None:
            generation_batch.batch_status = TASK_STATUS_FAILURE
            generation_batch.finished_at = DateTimeUtil.now_utc()
            repository.save(generation_batch)
            repository.session.commit()


def _create_session(payload: dict) -> Session:
    """为覆盖率分析任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
