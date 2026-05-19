"""
@Date: 2026-05-19
@Author: xisy
@Discription: 课件模块任务执行能力
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import TASK_STATUS_FAILURE, TASK_STATUS_PENDING, TASK_STATUS_PROCESSING, TASK_STATUS_SUCCESS
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode, get_task_error_code
from app.modules.courseware.repository import CoursewareRepository
from app.modules.courseware.service import CoursewareService
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.utils import DateTimeUtil


def run_generate_courseware_task(payload: dict) -> dict[str, int | str | None]:
    """执行 Raccoon PPT 课件生成任务。"""
    session = _create_session(payload)
    repository = CoursewareRepository(session)
    task_repository = TaskCenterRepository(session)
    service = CoursewareService(session, repository)
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "课件生成任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        lesson_plan_id = int(payload["lesson_plan_id"])

        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_courseware_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_courseware_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_courseware_baseline"])
        session.commit()

        context = service.build_generation_context(generation_batch.id, lesson_plan_id)
        _mark_step(
            step_map["prepare_courseware_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "generation_batch_id": generation_batch.id,
                "curriculum_plan_id": context["curriculum_plan"].id,
                "lesson_plan_id": context["lesson_plan"].id,
                "knowledge_point_count": len(context["knowledge_points"]),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["generate_slide_deck"], TASK_STATUS_PROCESSING, 20, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="generate_slide_deck", progress_percent=30)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        deck = service.generate_slide_deck(context)
        _mark_step(
            step_map["generate_slide_deck"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"slide_count": len(deck.slides)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["create_raccoon_ppt_job"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="create_raccoon_ppt_job",
            progress_percent=45,
        )
        task_repository.save(task)
        task_repository.save(step_map["generate_slide_deck"])
        task_repository.save(step_map["create_raccoon_ppt_job"])
        session.commit()

        courseware_result, state = service.create_remote_courseware_result_from_deck(
            context=context,
            deck=deck,
            operator_user_id=payload.get("operator_user_id"),
        )
        normalized_status = state.status.lower()
        _mark_step(
            step_map["create_raccoon_ppt_job"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"raccoon_job_id": state.job_id, "raccoon_status": state.status},
            finished_at=DateTimeUtil.now_utc(),
        )

        if normalized_status == "succeeded":
            _mark_step(
                step_map["poll_raccoon_ppt_job"],
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"raccoon_status": state.status},
                started_at=DateTimeUtil.now_utc(),
                finished_at=DateTimeUtil.now_utc(),
            )
            _mark_step(
                step_map["archive_courseware_result"],
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"export_file_id": courseware_result.export_file_id},
                started_at=DateTimeUtil.now_utc(),
                finished_at=DateTimeUtil.now_utc(),
            )
            _mark_step(
                step_map["finalize_generation_batch"],
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"courseware_result_status": TASK_STATUS_SUCCESS},
                started_at=DateTimeUtil.now_utc(),
                finished_at=DateTimeUtil.now_utc(),
            )
            _mark_task(
                task,
                task_status=TASK_STATUS_SUCCESS,
                current_stage="finalize_generation_batch",
                progress_percent=100,
                result_json={
                    "generation_batch_id": generation_batch.id,
                    "courseware_result_id": courseware_result.id,
                    "export_file_id": courseware_result.export_file_id,
                    "raccoon_job_id": state.job_id,
                },
                finished_at=DateTimeUtil.now_utc(),
            )
        elif normalized_status in {"failed", "canceled"}:
            _mark_step(
                step_map["poll_raccoon_ppt_job"],
                TASK_STATUS_FAILURE,
                100,
                detail_json={"raccoon_status": state.status, "error": state.error_message},
                started_at=DateTimeUtil.now_utc(),
                finished_at=DateTimeUtil.now_utc(),
            )
            _mark_task(
                task,
                task_status=TASK_STATUS_FAILURE,
                current_stage="raccoon_task_failed",
                progress_percent=100,
                result_json={
                    "generation_batch_id": generation_batch.id,
                    "courseware_result_id": courseware_result.id,
                    "raccoon_job_id": state.job_id,
                    "raccoon_status": state.status,
                },
                finished_at=DateTimeUtil.now_utc(),
            )
        else:
            _mark_step(
                step_map["poll_raccoon_ppt_job"],
                TASK_STATUS_PROCESSING,
                80,
                detail_json={
                    "raccoon_status": state.status,
                    "raccoon_job_id": state.job_id,
                    "required_user_input": state.required_user_input,
                },
                started_at=DateTimeUtil.now_utc(),
            )
            _mark_task(
                task,
                task_status=TASK_STATUS_PROCESSING,
                current_stage="waiting_user_input" if normalized_status == "waiting_user_input" else "waiting_raccoon_result",
                progress_percent=80,
                result_json={
                    "generation_batch_id": generation_batch.id,
                    "courseware_result_id": courseware_result.id,
                    "raccoon_job_id": state.job_id,
                    "raccoon_status": state.status,
                },
            )

        for step in step_map.values():
            task_repository.save(step)
        task_repository.save(task)
        session.commit()
        return {
            "generation_batch_id": generation_batch.id,
            "courseware_result_id": courseware_result.id,
            "export_file_id": courseware_result.export_file_id,
            "raccoon_status": state.status,
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
            "prepare_courseware_baseline",
            "generate_slide_deck",
            "create_raccoon_ppt_job",
            "poll_raccoon_ppt_job",
            "archive_courseware_result",
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
    repository: CoursewareRepository,
    payload: dict,
    exc: Exception,
) -> None:
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = get_task_error_code(exc, BusinessErrorCode.COURSEWARE_TASK_FAILED)
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)
    for step_code in (
        "prepare_courseware_baseline",
        "generate_slide_deck",
        "create_raccoon_ppt_job",
        "poll_raccoon_ppt_job",
        "archive_courseware_result",
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
    """为课件生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
