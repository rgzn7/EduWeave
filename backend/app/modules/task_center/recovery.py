"""
@Date: 2026-05-22
@Author: xisy
@Discription: 任务恢复能力——任务级失败重试与僵尸任务回收
"""

from sqlalchemy import func, or_, select, text

from app.core.config import get_settings
from app.core.constants import (
    ASSESSMENT_GENERATE_TASK_TYPE,
    COURSEWARE_GENERATE_TASK_TYPE,
    COVERAGE_ANALYZE_TASK_TYPE,
    CURRICULUM_GENERATE_TASK_TYPE,
    EXTERNAL_WAIT_TASK_STAGES,
    HOMEWORK_GENERATE_TASK_TYPE,
    KNOWLEDGE_EXTRACT_TASK_TYPE,
    LESSON_PLAN_GENERATE_TASK_TYPE,
    PROFILE_EXTRACT_TASK_TYPE,
    RETRYABLE_TASK_ERROR_CODES,
    TASK_HANDLER_UNREGISTERED_ERROR_CODE,
    TASK_STALE_TIMEOUT_ERROR_CODE,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    TEXTBOOK_PARSE_TASK_TYPE,
    TEXTBOOK_REPARSE_TASK_TYPE,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.logging import get_logger
from app.modules.p0_models import TaskRecord
from app.modules.task_center.heartbeat import StaleAttemptError, start_attempt
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.queue.app import celery_app, dispatch_task
from app.shared.utils import DateTimeUtil

logger = get_logger(__name__)

# 任务类型到处理函数路径的注册表，是 reaper/重试重新派发时取回 callable 的唯一来源
# （callable_path 未落库）。新增任务类型必须在此登记，否则无法被自动重排。
TASK_HANDLER_REGISTRY: dict[str, str] = {
    PROFILE_EXTRACT_TASK_TYPE: "app.modules.learner_profile.tasks.run_extract_task",
    TEXTBOOK_PARSE_TASK_TYPE: "app.modules.parsing.tasks.run_parse_task",
    TEXTBOOK_REPARSE_TASK_TYPE: "app.modules.parsing.tasks.run_reparse_task",
    KNOWLEDGE_EXTRACT_TASK_TYPE: "app.modules.knowledge.tasks.run_extract_task",
    CURRICULUM_GENERATE_TASK_TYPE: "app.modules.curriculum.tasks.run_generate_curriculum_task",
    LESSON_PLAN_GENERATE_TASK_TYPE: "app.modules.lesson_plan.tasks.run_generate_lesson_plan_task",
    ASSESSMENT_GENERATE_TASK_TYPE: "app.modules.assessment.tasks.run_generate_assessment_task",
    HOMEWORK_GENERATE_TASK_TYPE: "app.modules.homework.tasks.run_generate_homework_task",
    COURSEWARE_GENERATE_TASK_TYPE: "app.modules.courseware.tasks.run_generate_courseware_task",
    COVERAGE_ANALYZE_TASK_TYPE: "app.modules.coverage.tasks.run_analyze_coverage_task",
}

_STALE_REAP_BATCH_LIMIT = 50
_ERROR_MESSAGE_MAX_LENGTH = 500

# 阶段级 stale 阈值覆盖（秒）：按 (task_type, current_stage) 命中后替换默认 task_stale_threshold_seconds。
# 知识抽取的 LLM 阶段单次抽取很慢，130 页教材合理用时即达 30+ 分钟，沿用默认阈值会误判。
STAGE_STALE_OVERRIDES: dict[tuple[str, str], int] = {
    (KNOWLEDGE_EXTRACT_TASK_TYPE, "invoke_llm_extract"): 3600,
    (LESSON_PLAN_GENERATE_TASK_TYPE, "invoke_llm_lesson_plan"): 3600,
    (COVERAGE_ANALYZE_TASK_TYPE, "invoke_llm_coverage"): 1800,
    (TEXTBOOK_PARSE_TASK_TYPE, "poll_mineru"): 1800,
    (TEXTBOOK_REPARSE_TASK_TYPE, "poll_mineru"): 1800,
}


def is_retryable_error(exc: Exception | None) -> bool:
    """判断异常是否值得重试。

    业务校验类 AppException（如各类 NOT_FOUND、BASELINE_INVALID）重试无意义；
    基础设施/外部依赖类瞬时错误与意外异常默认可重试。
    StaleAttemptError 永远不可重试——被抢占的 worker 必须安静退出，不能再触发新一轮重排。
    """
    if exc is None:
        return True
    if isinstance(exc, StaleAttemptError):
        return False
    if isinstance(exc, AppException):
        return exc.code.value in RETRYABLE_TASK_ERROR_CODES
    return True


def build_dispatch_payload(task: TaskRecord) -> dict:
    """从任务记录重建派发 payload。

    create_task 落库的 payload_json 不含 task_record_id、operator_user_id
    （后者是独立列），需补齐这些 worker 必读字段。execution_attempt_id 必须
    一同携带，worker 才能在 CAS UPDATE 中校验自己是否仍是当前权威执行者。
    数据库连接串不在此重建，由 dispatch_task 在内联执行时按需注入。
    """
    payload = dict(task.payload_json or {})
    payload["task_record_id"] = task.id
    payload["generation_batch_id"] = task.generation_batch_id
    payload["operator_user_id"] = task.operator_user_id
    if task.execution_attempt_id:
        payload["execution_attempt_id"] = task.execution_attempt_id
    return payload


def requeue_or_fail_task(
    task_repository: TaskCenterRepository,
    task: TaskRecord,
    *,
    exc: Exception | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    fallback_error_code: BusinessErrorCode | None = None,
    force_retryable: bool | None = None,
) -> bool:
    """对失败或僵尸任务执行“重排重试或判终态失败”决策。

    返回 True 表示已重排（task_status=pending 并重新派发）；
    返回 False 表示已判终态失败（task_status=failure）。
    调用方仅需在返回 False 时补充模块级联失败副作用（如生成批次状态）。

    StaleAttemptError 视为 no-op：被抢占的 worker 不应触发任何 task_record 写入，
    直接返回 False（不重排、不判失败）。新权威 worker 已在运行，状态由其推进。
    """
    if isinstance(exc, StaleAttemptError):
        logger.info(
            "忽略被抢占 worker 的 StaleAttemptError，跳过重排/判失败",
            task_id=task.id,
            task_type=task.task_type,
        )
        return False

    settings = get_settings()
    now = DateTimeUtil.now_utc()
    retryable = force_retryable if force_retryable is not None else is_retryable_error(exc)
    resolved_error_code = _resolve_error_code(exc, error_code, fallback_error_code)
    resolved_error_message = _resolve_error_message(exc, error_message)
    callable_path = TASK_HANDLER_REGISTRY.get(task.task_type)
    steps = task_repository.list_task_steps(task.id)

    if retryable and task.retry_count < task.max_retry_count and callable_path is None:
        logger.error("任务类型未注册处理器，无法重排", task_id=task.id, task_type=task.task_type)
        resolved_error_code = TASK_HANDLER_UNREGISTERED_ERROR_CODE
        resolved_error_message = f"任务类型 {task.task_type} 未注册处理器，无法自动重试"
        retryable = False

    if retryable and task.retry_count < task.max_retry_count:
        # 先 best-effort 终止原 worker；attempt_id 轮换是最终安全网，revoke 没生效也不会双写
        _revoke_worker_if_present(task)
        task.retry_count += 1
        task.task_status = TASK_STATUS_PENDING
        task.current_stage = None
        task.progress_percent = 0
        task.started_at = None
        task.worker_task_id = None
        task.last_heartbeat_at = None
        task.last_error_code = resolved_error_code
        task.last_error_message = _truncate(resolved_error_message)
        task_repository.save(task)
        for step in steps:
            step.step_status = TASK_STATUS_PENDING
            step.progress_percent = 0
            step.started_at = None
            step.finished_at = None
            task_repository.save(step)
        # 轮换 attempt_id：原 worker 即使仍在跑，下一次 CAS UPDATE 会因 rowcount==0 退出
        new_attempt_id = start_attempt(task_repository, task.id)
        task.execution_attempt_id = new_attempt_id
        task_repository.session.commit()
        countdown = settings.task_retry_backoff_base_seconds * (2 ** (task.retry_count - 1))
        _redispatch_task(task, callable_path, countdown, task_repository.session)
        logger.info(
            "任务已重排重试",
            task_id=task.id,
            task_type=task.task_type,
            retry_count=task.retry_count,
            new_attempt_id=new_attempt_id,
        )
        return True

    task.task_status = TASK_STATUS_FAILURE
    task.last_error_code = resolved_error_code
    task.last_error_message = _truncate(resolved_error_message)
    task.finished_at = now
    task_repository.save(task)
    # 仅标记首个未成功步骤为失败，后续步骤保持 pending，表示任务终止在该阶段
    for step in steps:
        if step.step_status == TASK_STATUS_SUCCESS:
            continue
        step.step_status = TASK_STATUS_FAILURE
        step.detail_json = {"error": _truncate(resolved_error_message)}
        step.finished_at = now
        task_repository.save(step)
        break
    task_repository.session.commit()
    logger.info(
        "任务判终态失败",
        task_id=task.id,
        task_type=task.task_type,
        error_code=resolved_error_code,
    )
    return False


def _stage_threshold(task: TaskRecord, default_threshold: int) -> int:
    """按 (task_type, current_stage) 命中阶段级阈值覆盖。"""
    if task.current_stage is None:
        return default_threshold
    return STAGE_STALE_OVERRIDES.get((task.task_type, task.current_stage), default_threshold)


def reap_stale_tasks_once(session, *, threshold_seconds: int, limit: int = _STALE_REAP_BATCH_LIMIT) -> dict[str, int]:
    """扫描一批僵尸任务并逐条重排或判失败。

    僵尸判定：
    - task_status 仍为 processing
    - COALESCE(last_heartbeat_at, updated_at) 超过阈值未更新
      （长任务通过 TaskHeartbeat.touch/tick 主动刷 heartbeat，业务进度推进同步刷 updated_at；
       历史在途 / 短任务无 heartbeat 时退化为 updated_at 判定，与旧行为一致）
    - 不在等待外部结果的合法停泊阶段（EXTERNAL_WAIT_TASK_STAGES，如 Raccoon PPT 远程轮询）

    阈值比较使用数据库自身时钟（NOW()），规避应用与 MySQL 的时区差异。
    候选集合用默认阈值粗筛后，再按 STAGE_STALE_OVERRIDES 在 Python 端做阶段级二次校验，
    避免 SQL 里写一个巨大的 CASE WHEN。
    """
    interval_clause = text(f"INTERVAL {int(threshold_seconds)} SECOND")
    stale_cutoff = func.date_sub(func.now(), interval_clause)
    activity_at = func.coalesce(TaskRecord.last_heartbeat_at, TaskRecord.updated_at)
    candidate_tasks = list(
        session.scalars(
            select(TaskRecord)
            .where(
                TaskRecord.task_status == TASK_STATUS_PROCESSING,
                activity_at < stale_cutoff,
                or_(
                    TaskRecord.current_stage.is_(None),
                    TaskRecord.current_stage.not_in(tuple(EXTERNAL_WAIT_TASK_STAGES)),
                ),
            )
            .order_by(activity_at.asc())
            .limit(limit)
        )
    )
    task_repository = TaskCenterRepository(session)
    requeued_count = 0
    failed_count = 0
    skipped_count = 0
    for task in candidate_tasks:
        # 阶段级阈值：知识抽取等已知长阶段适当放宽
        stage_threshold = _stage_threshold(task, threshold_seconds)
        if stage_threshold > threshold_seconds:
            # 用 DB 自身时钟做秒级差值比较，规避应用与 MySQL 的时区差异
            elapsed_seconds = session.execute(
                text(
                    "SELECT TIMESTAMPDIFF(SECOND, "
                    "COALESCE(last_heartbeat_at, updated_at), NOW(3)) "
                    "FROM task_record WHERE id = :task_id"
                ),
                {"task_id": task.id},
            ).scalar()
            if elapsed_seconds is not None and int(elapsed_seconds) < stage_threshold:
                skipped_count += 1
                continue
        retried = requeue_or_fail_task(
            task_repository,
            task,
            error_code=TASK_STALE_TIMEOUT_ERROR_CODE,
            error_message="任务执行超时，worker 可能已崩溃，已由 reaper 回收",
            force_retryable=True,
        )
        if retried:
            requeued_count += 1
        else:
            failed_count += 1
    return {
        "scanned": len(candidate_tasks),
        "requeued": requeued_count,
        "failed": failed_count,
        "skipped_by_stage": skipped_count,
    }


@celery_app.task(name="system.reap_stale_tasks")
def reap_stale_tasks() -> dict[str, int]:
    """周期回收僵尸任务的 Celery Beat 任务。"""
    settings = get_settings()
    session = SessionLocal()
    try:
        summary = reap_stale_tasks_once(session, threshold_seconds=settings.task_stale_threshold_seconds)
        if summary["scanned"]:
            logger.info("僵尸任务回收完成", **summary)
        return summary
    finally:
        session.close()


def _revoke_worker_if_present(task: TaskRecord) -> None:
    """best-effort 终止原 Celery worker 上的任务。

    eager 模式或 broker 不可达时静默忽略——attempt_id CAS 是最终安全网，
    revoke 没生效时原 worker 下次写库会 rowcount==0 自动退出。
    """
    if not task.worker_task_id:
        return
    if get_settings().task_eager_mode:
        return
    try:
        celery_app.control.revoke(task.worker_task_id, terminate=True, signal="SIGKILL")
    except Exception as exc:  # noqa: BLE001
        logger.warning("revoke 原 worker 失败，依赖 attempt_id 兜底", task_id=task.id, error=str(exc))


def _redispatch_task(task: TaskRecord, callable_path: str, countdown: int, session) -> None:
    """重新派发任务。

    eager 内联模式下重跑异常已由内层落库收敛，外层吞掉避免污染调用栈；
    异步模式下派发异常需抛出，避免任务静默卡在 pending。
    """
    payload = build_dispatch_payload(task)
    if get_settings().task_eager_mode:
        try:
            dispatch_task(callable_path, payload, queue=task.queue_name, session=session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("内联重试重跑异常，已由内层落库收敛", task_id=task.id, error=str(exc))
    else:
        dispatch_task(callable_path, payload, queue=task.queue_name, countdown=countdown)


def _resolve_error_code(
    exc: Exception | None,
    error_code: str | None,
    fallback_error_code: BusinessErrorCode | None,
) -> str | None:
    """解析落库错误码。"""
    if error_code:
        return error_code
    if isinstance(exc, AppException):
        return exc.code.value
    if fallback_error_code is not None:
        return fallback_error_code.value
    if exc is not None:
        return type(exc).__name__
    return None


def _resolve_error_message(exc: Exception | None, error_message: str | None) -> str | None:
    """解析落库错误信息。"""
    if error_message:
        return error_message
    if isinstance(exc, AppException):
        return exc.message
    if exc is not None:
        return str(exc)
    return None


def _truncate(value: str | None, limit: int = _ERROR_MESSAGE_MAX_LENGTH) -> str | None:
    """裁剪错误信息以适配 last_error_message 列长度。"""
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit]
