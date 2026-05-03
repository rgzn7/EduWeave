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
            raise RuntimeError("覆盖率分析任务不存在")
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

        courseware_result = repository.get_courseware_result_by_batch(generation_batch.id)
        if courseware_result is None or courseware_result.result_status != TASK_STATUS_SUCCESS:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课件结果未完成，无法分析覆盖率")

        _mark_step(
            step_map["prepare_coverage_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "generation_batch_id": generation_batch.id,
                "knowledge_version_id": generation_batch.knowledge_version_id,
                "courseware_result_id": courseware_result.id,
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
    task = task_repository.get_task_by_id(payload["task_record_id"])
    generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
    if generation_batch is not None:
        generation_batch.batch_status = TASK_STATUS_FAILURE
        generation_batch.finished_at = DateTimeUtil.now_utc()
        repository.save(generation_batch)
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = getattr(exc, "code", None).value if isinstance(exc, AppException) else "COVERAGE_TASK_FAILED"
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)
    for step_code in (
        "prepare_coverage_baseline",
        "collect_artifact_refs",
        "persist_coverage_report",
        "write_generation_trace",
        "finalize_generation_batch",
    ):
        step = task_repository.get_task_step(payload["task_record_id"], step_code)
        if step is None or step.step_status == TASK_STATUS_SUCCESS:
            continue
        step.step_status = TASK_STATUS_FAILURE
        step.detail_json = {"error": str(exc)}
        step.finished_at = DateTimeUtil.now_utc()
        task_repository.save(step)
        break
    repository.session.commit()


def _create_session(payload: dict) -> Session:
    """为覆盖率分析任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
