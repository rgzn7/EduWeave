"""
@Date: 2026-05-30
@Author: xisy
@Discription: 教案模块任务执行能力
"""

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.constants import (
    COVERAGE_ANALYZE_TASK_TYPE,
    GENERATION_QUEUE_NAME,
    LESSON_PLAN_ITEM_STATUS_FAILURE,
    LESSON_PLAN_ITEM_STATUS_PENDING,
    LESSON_PLAN_ITEM_STATUS_PROCESSING,
    LESSON_PLAN_ITEM_STATUS_SUCCESS,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.quality_report.service import CoverageService
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.modules.p0_models import LessonPlan, LessonPlanGenerationItem, TaskRecord
from app.modules.task_center.heartbeat import (
    StaleAttemptError,
    TaskHeartbeat,
    TaskProgressPulse,
    dispatch_with_attempt,
    ensure_attempt,
)
from app.modules.task_center.progress import assign_monotonic_progress
from app.modules.task_center.recovery import is_retryable_error, requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, LlmUsage, OpenAICompatibleLlmService, load_evidence_image_data_urls
from app.shared.utils import DateTimeUtil
from app.shared.utils.chapter_range_util import build_chapter_range_selection, filter_knowledge_points_by_chapter_selection

logger = structlog.get_logger(__name__)


def _load_evidence_images(repository: LessonPlanRepository, knowledge_points: list) -> list[str]:
    """按配置加载知识点证据关联的教材图片（关闭或无图时返回空，零影响）。"""
    settings = get_settings()
    if not settings.llm_multimodal_enabled:
        return []
    knowledge_point_ids = [point.id for point in knowledge_points]
    assets = repository.list_evidence_image_assets(knowledge_point_ids)
    data_urls = load_evidence_image_data_urls(
        assets=assets,
        max_images=settings.llm_multimodal_max_images,
    )
    logger.info(
        "lesson_plan_evidence_images_loaded",
        knowledge_point_count=len(knowledge_point_ids),
        asset_count=len(assets),
        loaded_image_count=len(data_urls),
    )
    return data_urls


def _summarize_llm_usage(usage_records: list[LlmUsage]) -> dict[str, int]:
    """聚合教案生成各课次的 LLM 使用量，用于上报到任务步骤 detail_json。

    含 call_count（含修复重试），便于观测 cached_tokens 命中曲线（首次为 0、之后渐升）。
    """
    if not usage_records:
        return {
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
        }
    return {
        "call_count": len(usage_records),
        "prompt_tokens": sum(item.prompt_tokens for item in usage_records),
        "completion_tokens": sum(item.completion_tokens for item in usage_records),
        "total_tokens": sum(item.total_tokens for item in usage_records),
        "cached_tokens": sum(item.cached_tokens for item in usage_records),
    }


def _summarize_generation_item_usage(items: list[LessonPlanGenerationItem]) -> dict[str, int]:
    """聚合课次中间结果中的 LLM 用量。"""
    summary = {
        "call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
    }
    for item in items:
        usage = item.llm_usage_json if isinstance(item.llm_usage_json, dict) else {}
        for key in summary:
            value = usage.get(key)
            if isinstance(value, int):
                summary[key] += value
    return summary


class LessonPlanSessionGenerationFailed(AppException):
    """单课次教案生成失败，携带可落库的课次级详情。"""

    def __init__(
        self,
        *,
        lesson_session: dict[str, Any],
        retry_count: int,
        exc: Exception,
        total_sessions: int,
        processed_sessions: int,
        parallel_limit: int,
    ) -> None:
        class_session_no = int(lesson_session.get("session_no") or 0)
        lesson_title = str(lesson_session.get("title") or "")
        code = exc.code if isinstance(exc, AppException) else BusinessErrorCode.LESSON_PLAN_TASK_FAILED
        message = exc.message if isinstance(exc, AppException) else str(exc)
        retryable = _is_retryable_lesson_session_error(exc)
        details = {
            "processed_sessions": processed_sessions,
            "total_sessions": total_sessions,
            "parallel_limit": parallel_limit,
            "failed_session_no": class_session_no,
            "failed_session_title": lesson_title,
            "session_retry_count": retry_count,
            "last_error_code": code.value,
            "last_error_message": message,
            "last_error_detail": _extract_safe_error_detail(exc),
            "retryable": retryable,
        }
        super().__init__(code, message, details)
        self.lesson_session = lesson_session
        self.retry_count = retry_count
        self.original_exc = exc


def _is_retryable_lesson_session_error(exc: Exception) -> bool:
    """判断单课次失败是否值得业务级重试。"""
    if isinstance(exc, AppException) and isinstance(exc.details, dict) and exc.details.get("retryable") is False:
        return False
    return is_retryable_error(exc)


def _extract_safe_error_detail(exc: Exception) -> dict[str, Any] | None:
    """提取 AppException 中已脱敏的错误详情。"""
    if isinstance(exc, AppException) and isinstance(exc.details, dict):
        return exc.details
    return None


def _generate_single_lesson_plan(
    *,
    llm_service: OpenAICompatibleLlmService,
    stable_messages: list[ChatMessage],
    lesson_session: dict[str, Any],
    index: int,
    cache_biz_key: str,
    cache_user_id: int | None,
    knowledge_point_ids: set[int],
) -> dict[str, Any]:
    """生成单课次教案；仅做 LLM 调用、结果校验与 usage 内存收集。"""
    class_session_no = int(lesson_session["session_no"])
    usage_records: list[LlmUsage] = []
    llm_messages = _build_lesson_plan_messages(
        stable_messages=stable_messages,
        target_lesson_session=lesson_session,
    )
    generation_result = llm_service.generate_structured_output(
        messages=llm_messages,
        response_model=LessonPlanGenerationResult,
        cache_biz_key=cache_biz_key,
        stable_prefix_message_count=len(stable_messages),
        cache_user_id=cache_user_id,
        on_usage=usage_records.append,
        strict_schema=True,
    )
    _validate_lesson_plan_result(
        generation_result,
        expected_session_no=class_session_no,
        knowledge_point_ids=knowledge_point_ids,
    )
    return {
        "index": index,
        "class_session_no": class_session_no,
        "lesson_session": lesson_session,
        "generation_result": generation_result,
        "usage_records": usage_records,
    }


def _generate_single_lesson_plan_with_retry(
    *,
    llm_service: OpenAICompatibleLlmService,
    stable_messages: list[ChatMessage],
    lesson_session: dict[str, Any],
    index: int,
    cache_biz_key: str,
    cache_user_id: int | None,
    knowledge_point_ids: set[int],
) -> dict[str, Any]:
    """带课次级退避重试的单课次教案生成。"""
    settings = get_settings()
    max_retries = settings.lesson_plan_session_max_retries
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = _generate_single_lesson_plan(
                llm_service=llm_service,
                stable_messages=stable_messages,
                lesson_session=lesson_session,
                index=index,
                cache_biz_key=cache_biz_key,
                cache_user_id=cache_user_id,
                knowledge_point_ids=knowledge_point_ids,
            )
            result["session_retry_count"] = attempt
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_lesson_session_error(exc):
                setattr(exc, "lesson_plan_session_retry_count", attempt)
                raise
            time.sleep(settings.lesson_plan_session_retry_base_seconds * (2**attempt))
    if last_exc is not None:
        raise last_exc
    raise AppException(BusinessErrorCode.LESSON_PLAN_TASK_FAILED, "教案课次生成失败")


def _update_lesson_plan_llm_progress(
    *,
    heartbeat: TaskHeartbeat,
    step_id: int,
    completed_sessions: int,
    total_sessions: int,
    class_session_no: int,
    parallel_limit: int,
    cache_warmup_completed: bool,
) -> None:
    """主线程刷新教案 LLM 阶段进度。"""
    progress_percent = int(100 * completed_sessions / max(total_sessions, 1))
    if completed_sessions > 0:
        task_progress = 40 + int(40 * completed_sessions / max(total_sessions, 1))
        heartbeat.tick(progress_percent=task_progress, current_stage="invoke_llm_lesson_plan")
    detail_json = {
        "processed_sessions": completed_sessions,
        "total_sessions": total_sessions,
        "parallel_limit": parallel_limit,
        "cache_warmup_completed": cache_warmup_completed,
    }
    if completed_sessions > 0:
        detail_json["last_completed_class_session_no"] = class_session_no
    heartbeat.update_step_detail(
        step_id=step_id,
        progress_percent=progress_percent,
        detail_json=detail_json,
    )


def _assert_generation_item_attempt(repository: LessonPlanRepository, task_id: int, attempt_id: str) -> None:
    """锁定任务行并确认当前 worker 仍是权威 attempt。"""
    current_attempt = repository.session.execute(
        select(TaskRecord.execution_attempt_id).where(TaskRecord.id == task_id).with_for_update()
    ).scalar_one_or_none()
    if current_attempt is not None and current_attempt != attempt_id:
        raise StaleAttemptError(task_id, attempt_id)


def _mark_generation_item_processing(
    repository: LessonPlanRepository,
    item: LessonPlanGenerationItem,
    *,
    task_id: int,
    attempt_id: str,
) -> None:
    """标记课次进入生成中状态。"""
    _assert_generation_item_attempt(repository, task_id, attempt_id)
    item.item_status = LESSON_PLAN_ITEM_STATUS_PROCESSING
    item.last_error_code = None
    item.last_error_message = None
    item.last_error_detail_json = None
    repository.save(item)
    repository.session.commit()


def _mark_generation_item_success(
    repository: LessonPlanRepository,
    item: LessonPlanGenerationItem,
    result: dict[str, Any],
    *,
    task_id: int,
    attempt_id: str,
) -> None:
    """保存单课次成功生成的中间结果。"""
    _assert_generation_item_attempt(repository, task_id, attempt_id)
    generation_result: LessonPlanGenerationResult = result["generation_result"]
    lesson_session = result["lesson_session"]
    item.item_status = LESSON_PLAN_ITEM_STATUS_SUCCESS
    item.lesson_title = generation_result.lesson_title
    item.summary_text = generation_result.summary_text
    item.content_json = _build_lesson_plan_content_json(
        generation_result,
        target_lesson_session=lesson_session,
    )
    item.llm_usage_json = _summarize_llm_usage(result["usage_records"])
    item.retry_count = int(result.get("session_retry_count") or 0)
    item.last_error_code = None
    item.last_error_message = None
    item.last_error_detail_json = None
    repository.save(item)
    repository.session.commit()


def _mark_generation_item_failure(
    repository: LessonPlanRepository,
    item: LessonPlanGenerationItem,
    failed_exc: LessonPlanSessionGenerationFailed,
    *,
    task_id: int,
    attempt_id: str,
) -> None:
    """保存单课次终态失败信息。"""
    _assert_generation_item_attempt(repository, task_id, attempt_id)
    item.item_status = LESSON_PLAN_ITEM_STATUS_FAILURE
    item.lesson_title = failed_exc.details.get("failed_session_title") if isinstance(failed_exc.details, dict) else item.lesson_title
    item.retry_count = failed_exc.retry_count
    item.last_error_code = failed_exc.code.value
    item.last_error_message = failed_exc.message[:500]
    item.last_error_detail_json = failed_exc.details
    repository.save(item)
    repository.session.commit()


def _generate_remaining_lesson_plans_in_parallel(
    *,
    repository: LessonPlanRepository,
    llm_service: OpenAICompatibleLlmService,
    stable_messages: list[ChatMessage],
    lesson_session_entries: list[tuple[int, dict[str, Any]]],
    item_by_session_no: dict[int, LessonPlanGenerationItem],
    cache_biz_key: str,
    cache_user_id: int | None,
    knowledge_point_ids: set[int],
    heartbeat: TaskHeartbeat,
    step_id: int,
    task_id: int,
    attempt_id: str,
    parallel_limit: int,
    total_sessions: int,
    completed_sessions: int,
) -> tuple[list[dict[str, Any]], list[LlmUsage]]:
    """并发生成第 2 课及之后课次；数据库状态只由主线程更新。"""
    results: list[dict[str, Any]] = []
    usage_records: list[LlmUsage] = []
    futures: list[Future] = []
    with ThreadPoolExecutor(max_workers=parallel_limit, thread_name_prefix="lesson-plan") as executor:
        future_session_map: dict[Future, dict[str, Any]] = {}
        for index, lesson_session in lesson_session_entries:
            class_session_no = int(lesson_session["session_no"])
            _mark_generation_item_processing(
                repository,
                item_by_session_no[class_session_no],
                task_id=task_id,
                attempt_id=attempt_id,
            )
            future = executor.submit(
                _generate_single_lesson_plan_with_retry,
                llm_service=llm_service,
                stable_messages=stable_messages,
                lesson_session=lesson_session,
                index=index,
                cache_biz_key=cache_biz_key,
                cache_user_id=cache_user_id,
                knowledge_point_ids=knowledge_point_ids,
            )
            futures.append(
                future
            )
            future_session_map[future] = lesson_session
        try:
            for future in as_completed(futures):
                lesson_session = future_session_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_exc = LessonPlanSessionGenerationFailed(
                        lesson_session=lesson_session,
                        retry_count=int(getattr(exc, "lesson_plan_session_retry_count", 0)),
                        exc=exc,
                        total_sessions=total_sessions,
                        processed_sessions=completed_sessions,
                        parallel_limit=parallel_limit,
                    )
                    _mark_generation_item_failure(
                        repository,
                        item_by_session_no[int(lesson_session["session_no"])],
                        failed_exc,
                        task_id=task_id,
                        attempt_id=attempt_id,
                    )
                    raise failed_exc from exc
                completed_sessions += 1
                results.append(result)
                usage_records.extend(result["usage_records"])
                _mark_generation_item_success(
                    repository,
                    item_by_session_no[result["class_session_no"]],
                    result,
                    task_id=task_id,
                    attempt_id=attempt_id,
                )
                _update_lesson_plan_llm_progress(
                    heartbeat=heartbeat,
                    step_id=step_id,
                    completed_sessions=completed_sessions,
                    total_sessions=total_sessions,
                    class_session_no=result["class_session_no"],
                    parallel_limit=parallel_limit,
                    cache_warmup_completed=True,
                )
        except Exception:
            for pending_future in futures:
                pending_future.cancel()
            raise
    return results, usage_records


def _resolve_last_completed_session_no(
    generation_items: list[LessonPlanGenerationItem],
    lesson_sessions: list[dict[str, Any]],
) -> int:
    """解析最近完成课次号，用于进度详情兜底。"""
    completed_session_nos = [
        int(item.class_session_no)
        for item in generation_items
        if item.item_status == LESSON_PLAN_ITEM_STATUS_SUCCESS
    ]
    if completed_session_nos:
        return max(completed_session_nos)
    return int(lesson_sessions[0]["session_no"])


def _persist_ready_lesson_plans(
    *,
    repository: LessonPlanRepository,
    curriculum_plan_id: int,
    generation_batch_id: int,
    generation_items: list[LessonPlanGenerationItem],
    created_by: int | None,
) -> list[int]:
    """把全部成功的中间结果转成正式教案，已存在的正式教案直接复用。"""
    existing_lesson_plans = repository.list_lesson_plans_by_batch(generation_batch_id)
    existing_by_session_no = {
        int(lesson_plan.class_session_no): lesson_plan
        for lesson_plan in existing_lesson_plans
        if lesson_plan.class_session_no is not None
    }
    lesson_plan_ids: list[int] = []
    next_version_no = repository.get_next_lesson_plan_version_no(curriculum_plan_id)
    created_count = 0
    for item in sorted(generation_items, key=lambda value: int(value.class_session_no)):
        class_session_no = int(item.class_session_no)
        existing = existing_by_session_no.get(class_session_no)
        if existing is not None:
            lesson_plan_ids.append(existing.id)
            continue
        if item.content_json is None:
            raise AppException(
                BusinessErrorCode.LESSON_PLAN_TASK_FAILED,
                "教案课次中间结果缺少内容，无法转正式教案",
                {"class_session_no": class_session_no},
            )
        lesson_plan = repository.create_lesson_plan(
            LessonPlan(
                curriculum_plan_id=curriculum_plan_id,
                generation_batch_id=generation_batch_id,
                class_session_no=class_session_no,
                version_no=next_version_no + created_count,
                lesson_title=item.lesson_title or f"第{class_session_no}课教案",
                style_code="standard",
                version_status=VERSION_STATUS_READY,
                summary_text=item.summary_text,
                content_json=item.content_json,
                export_file_id=None,
                created_by=created_by,
            )
        )
        created_count += 1
        lesson_plan_ids.append(lesson_plan.id)
    return lesson_plan_ids


def run_generate_lesson_plan_task(payload: dict) -> dict[str, int | str]:
    """执行教案生成任务。"""
    session = _create_session(payload)
    repository = LessonPlanRepository(session)
    task_repository = TaskCenterRepository(session)
    llm_service = OpenAICompatibleLlmService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()
    lesson_task_completed = False
    attempt_id = ensure_attempt(task_repository, payload["task_record_id"], payload.get("execution_attempt_id"))
    heartbeat = TaskHeartbeat(session, payload["task_record_id"], attempt_id)

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "教案生成任务不存在")
        if task.execution_attempt_id and task.execution_attempt_id != attempt_id:
            raise StaleAttemptError(task.id, attempt_id)
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        curriculum_plan = repository.get_curriculum_plan(payload["curriculum_plan_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        if curriculum_plan.project_id != generation_batch.project_id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲不属于当前生成批次")

        generation_batch.batch_status = TASK_STATUS_PROCESSING
        generation_batch.started_at = generation_batch.started_at or now
        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_lesson_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_lesson_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        repository.save(generation_batch)
        task_repository.save(task)
        task_repository.save(step_map["prepare_lesson_baseline"])
        session.commit()

        if curriculum_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲版本不可用")
        project = repository.get_project(curriculum_plan.project_id)
        profile_version = repository.get_learner_profile_version(curriculum_plan.learner_profile_version_id)
        all_knowledge_points = repository.list_knowledge_points(generation_batch.knowledge_version_id)
        chapters = repository.list_chapter_nodes(generation_batch.knowledge_version_id)
        chapter_selection = build_chapter_range_selection(
            chapters=chapters,
            chapter_range_json=generation_batch.chapter_range_json,
        )
        knowledge_points = filter_knowledge_points_by_chapter_selection(
            knowledge_points=all_knowledge_points,
            selection=chapter_selection,
        )
        profile_records = repository.list_profile_records(curriculum_plan.learner_profile_version_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        if profile_version is None:
            raise AppException(BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND, "学情版本不存在")
        if not all_knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲绑定的知识版本缺少知识点")
        if not profile_records:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲绑定的学情版本缺少画像记录")

        lesson_sessions = _get_curriculum_lesson_sessions(curriculum_plan)
        _mark_step(
            step_map["prepare_lesson_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "curriculum_plan_id": curriculum_plan.id,
                "knowledge_version_id": curriculum_plan.knowledge_version_id,
                "learner_profile_version_id": curriculum_plan.learner_profile_version_id,
                "chapter_range_scoped": chapter_selection.is_scoped,
                "requested_chapter_ids": chapter_selection.requested_chapter_ids,
                "effective_chapter_ids": chapter_selection.effective_chapter_ids,
                "total_knowledge_version_point_count": len(all_knowledge_points),
                "knowledge_point_count": len(knowledge_points),
                "profile_record_count": len(profile_records),
                "lesson_session_count": len(lesson_sessions),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_lesson_plan"], TASK_STATUS_PROCESSING, 0, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_lesson_plan", progress_percent=40)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        evidence_images = _load_evidence_images(repository, knowledge_points)
        # 同一批次跨课次复用稳定前缀消息，让上游 prompt cache 在第 2 次起命中前缀缓存。
        stable_messages = _build_lesson_plan_stable_messages(
            project=project,
            generation_batch=generation_batch,
            curriculum_plan=curriculum_plan,
            profile_version=profile_version,
            knowledge_points=knowledge_points,
            profile_records=profile_records,
            evidence_images=evidence_images,
        )
        # cache_biz_key 按批次分片：同批 N 次课次共享同一上游缓存分片，跨批次互不污染。
        cache_biz_key = f"lesson-batch-{generation_batch.id}"
        cache_user_id = payload.get("operator_user_id")
        total_sessions = len(lesson_sessions)
        generation_items = repository.ensure_generation_items(
            generation_batch_id=generation_batch.id,
            task_record_id=task.id,
            lesson_sessions=lesson_sessions,
        )
        _assert_generation_item_attempt(repository, task.id, attempt_id)
        repository.session.commit()
        item_by_session_no = {int(item.class_session_no): item for item in generation_items}
        completed_sessions = sum(
            1 for item in generation_items if item.item_status == LESSON_PLAN_ITEM_STATUS_SUCCESS
        )
        pending_entries = [
            (index, lesson_session)
            for index, lesson_session in enumerate(lesson_sessions, start=1)
            if item_by_session_no[int(lesson_session["session_no"])].item_status
            in {LESSON_PLAN_ITEM_STATUS_PENDING, LESSON_PLAN_ITEM_STATUS_PROCESSING, LESSON_PLAN_ITEM_STATUS_FAILURE}
        ]
        parallel_limit = min(get_settings().lesson_plan_max_concurrency, max(len(pending_entries), 1))
        knowledge_point_ids = {point.id for point in knowledge_points}
        heartbeat.touch()
        _update_lesson_plan_llm_progress(
            heartbeat=heartbeat,
            step_id=step_map["invoke_llm_lesson_plan"].id,
            completed_sessions=completed_sessions,
            total_sessions=total_sessions,
            class_session_no=_resolve_last_completed_session_no(generation_items, lesson_sessions),
            parallel_limit=parallel_limit,
            cache_warmup_completed=completed_sessions > 0,
        )

        serial_entry: tuple[int, dict[str, Any]] | None = pending_entries[0] if pending_entries and completed_sessions == 0 else None
        remaining_entries = pending_entries[1:] if serial_entry is not None else pending_entries
        if serial_entry is not None:
            first_index, first_lesson_session = serial_entry
            first_class_session_no = int(first_lesson_session["session_no"])
            _mark_generation_item_processing(
                repository,
                item_by_session_no[first_class_session_no],
                task_id=task.id,
                attempt_id=attempt_id,
            )
            try:
                with TaskProgressPulse.from_session(
                    session,
                    task_id=task.id,
                    attempt_id=attempt_id,
                    current_stage="invoke_llm_lesson_plan",
                    start_progress=40,
                    max_progress=44,
                ):
                    first_result = _generate_single_lesson_plan_with_retry(
                        llm_service=llm_service,
                        stable_messages=stable_messages,
                        lesson_session=first_lesson_session,
                        index=first_index,
                        cache_biz_key=cache_biz_key,
                        cache_user_id=cache_user_id,
                        knowledge_point_ids=knowledge_point_ids,
                    )
            except Exception as exc:  # noqa: BLE001
                failed_exc = LessonPlanSessionGenerationFailed(
                    lesson_session=first_lesson_session,
                    retry_count=int(getattr(exc, "lesson_plan_session_retry_count", 0)),
                    exc=exc,
                    total_sessions=total_sessions,
                    processed_sessions=completed_sessions,
                    parallel_limit=parallel_limit,
                )
                _mark_generation_item_failure(
                    repository,
                    item_by_session_no[first_class_session_no],
                    failed_exc,
                    task_id=task.id,
                    attempt_id=attempt_id,
                )
                raise failed_exc from exc
            _mark_generation_item_success(
                repository,
                item_by_session_no[first_class_session_no],
                first_result,
                task_id=task.id,
                attempt_id=attempt_id,
            )
            completed_sessions += 1
            _update_lesson_plan_llm_progress(
                heartbeat=heartbeat,
                step_id=step_map["invoke_llm_lesson_plan"].id,
                completed_sessions=completed_sessions,
                total_sessions=total_sessions,
                class_session_no=first_result["class_session_no"],
                parallel_limit=parallel_limit,
                cache_warmup_completed=True,
            )

        if remaining_entries:
            with TaskProgressPulse.from_session(
                session,
                task_id=task.id,
                attempt_id=attempt_id,
                current_stage="invoke_llm_lesson_plan",
                start_progress=45,
                max_progress=79,
            ):
                _remaining_results, _remaining_usage_records = _generate_remaining_lesson_plans_in_parallel(
                    repository=repository,
                    llm_service=llm_service,
                    stable_messages=stable_messages,
                    lesson_session_entries=remaining_entries,
                    item_by_session_no=item_by_session_no,
                    cache_biz_key=cache_biz_key,
                    cache_user_id=cache_user_id,
                    knowledge_point_ids=knowledge_point_ids,
                    heartbeat=heartbeat,
                    step_id=step_map["invoke_llm_lesson_plan"].id,
                    task_id=task.id,
                    attempt_id=attempt_id,
                    parallel_limit=parallel_limit,
                    total_sessions=total_sessions,
                    completed_sessions=completed_sessions,
                )

        generation_items = repository.list_generation_items_by_batch(generation_batch.id)
        if any(item.item_status != LESSON_PLAN_ITEM_STATUS_SUCCESS for item in generation_items):
            failed_item = next(
                (item for item in generation_items if item.item_status == LESSON_PLAN_ITEM_STATUS_FAILURE),
                None,
            )
            last_error_detail = failed_item.last_error_detail_json if failed_item is not None else None
            retryable = True
            if isinstance(last_error_detail, dict) and isinstance(last_error_detail.get("retryable"), bool):
                retryable = bool(last_error_detail["retryable"])
            detail = {
                "processed_sessions": sum(
                    1 for item in generation_items if item.item_status == LESSON_PLAN_ITEM_STATUS_SUCCESS
                ),
                "total_sessions": total_sessions,
                "parallel_limit": parallel_limit,
                "failed_session_no": failed_item.class_session_no if failed_item is not None else None,
                "last_error_detail": last_error_detail,
                "retryable": retryable,
            }
            raise AppException(BusinessErrorCode.LESSON_PLAN_TASK_FAILED, "教案课次生成未全部成功", detail)

        _assert_generation_item_attempt(repository, task.id, attempt_id)
        lesson_plan_ids = _persist_ready_lesson_plans(
            repository=repository,
            curriculum_plan_id=curriculum_plan.id,
            generation_batch_id=generation_batch.id,
            generation_items=generation_items,
            created_by=payload.get("operator_user_id"),
        )

        generation_batch.lesson_plan_id = lesson_plan_ids[0]
        _mark_step(
            step_map["invoke_llm_lesson_plan"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "lesson_plan_count": len(lesson_plan_ids),
                "lesson_plan_ids": lesson_plan_ids,
                "llm_usage": _summarize_generation_item_usage(generation_items),
                "processed_sessions": total_sessions,
                "total_sessions": total_sessions,
                "last_completed_class_session_no": int(lesson_sessions[-1]["session_no"]),
                "parallel_limit": parallel_limit,
                "cache_warmup_completed": True,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_lesson_plan"], TASK_STATUS_PROCESSING, 45, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_lesson_plan", progress_percent=80)
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        _mark_step(
            step_map["persist_lesson_plan"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"lesson_plan_ids": lesson_plan_ids, "lesson_plan_count": len(lesson_plan_ids)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["finalize_generation_batch"], TASK_STATUS_PROCESSING, 70, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_generation_batch", progress_percent=90)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        coverage_service = CoverageService(session)
        coverage_task = coverage_service.create_coverage_task_if_needed(
            generation_batch_id=generation_batch.id,
            operator_user_id=payload.get("operator_user_id"),
            request_id=task.request_id,
        )
        finished_at = DateTimeUtil.now_utc()
        generation_batch.batch_status = TASK_STATUS_PROCESSING
        coverage_task_id = coverage_task.id if coverage_task is not None else None
        _mark_step(
            step_map["finalize_generation_batch"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "batch_status": TASK_STATUS_PROCESSING,
                "next_task_id": coverage_task_id,
                "next_task_type": COVERAGE_ANALYZE_TASK_TYPE if coverage_task_id is not None else None,
            },
            finished_at=finished_at,
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="finalize_generation_batch",
            progress_percent=100,
            result_json={
                "generation_batch_id": generation_batch.id,
                "curriculum_plan_id": curriculum_plan.id,
                "lesson_plan_id": lesson_plan_ids[0],
                "lesson_plan_ids": lesson_plan_ids,
                "lesson_plan_count": len(lesson_plan_ids),
                "coverage_task_id": coverage_task_id,
            },
            finished_at=finished_at,
        )
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        lesson_task_completed = True

        if coverage_task is not None:
            coverage_dispatch_payload: dict[str, object] = {
                "task_record_id": coverage_task.id,
                "generation_batch_id": generation_batch.id,
                "operator_user_id": payload.get("operator_user_id"),
            }
            if payload.get("generation_run_id") is not None:
                coverage_dispatch_payload["generation_run_id"] = payload.get("generation_run_id")
                # 同时把 generation_run_id 落到 coverage_task.payload_json，
                # 避免后续从 task 直接取时缺失
                merged_payload = dict(coverage_task.payload_json or {})
                merged_payload["generation_run_id"] = payload.get("generation_run_id")
                coverage_task.payload_json = merged_payload
                task_repository.save(coverage_task)
                session.commit()
            dispatch_result = dispatch_with_attempt(
                task_repository,
                task=coverage_task,
                callable_path="app.modules.quality_report.tasks.run_analyze_coverage_task",
                payload=coverage_dispatch_payload,
                queue=GENERATION_QUEUE_NAME,
            )
            if dispatch_result.worker_task_id:
                coverage_task.worker_task_id = dispatch_result.worker_task_id
                task_repository.save(coverage_task)
                session.commit()
        _notify_orchestrator_lesson_plan_success(session=session, task=task)
        return {
            "generation_batch_id": generation_batch.id,
            "curriculum_plan_id": curriculum_plan.id,
            "lesson_plan_id": lesson_plan_ids[0],
            "lesson_plan_ids": lesson_plan_ids,
            "lesson_plan_count": len(lesson_plan_ids),
            "coverage_task_id": coverage_task_id,
        }
    except StaleAttemptError:
        session.rollback()
        return {"stale_attempt": True}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        if not lesson_task_completed:
            _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


# 拆分为两段独立 system 提示，便于上游 prompt cache 命中前缀；调整任一段不击穿另一段缓存。
_LESSON_PLAN_ROLE_AND_SCHEMA_PROMPT = (
    "你是教案生成助手。请基于课程大纲中的 target_lesson_session、教材知识点和班级学情生成中文教师教案。"
    "learner_profile_version 是一个班级的学情：records 为全班各学生×学科画像，class_profile 为班级聚合画像"
    "（学科概览、共性强弱、高/中/低分层分组与教学建议）；教案须面向全班并兼顾分层，learner_adjustments 中体现差异化安排。"
    "必须严格输出 JSON 对象，字段如下，类型必须严格匹配："
    "lesson_title（字符串，不超过 255 字）；"
    "summary_text（字符串或 null）；"
    "course_overview（对象，必须且只能包含 audience、duration、focus 三个字符串字段，"
    "例如 {\"audience\": \"五年级学生\", \"duration\": \"40 分钟\", \"focus\": \"乘法分配律\"}）；"
    "material_list（字符串数组，每项是一句简述，例如 \"单词卡片若干\"）；"
    "core_knowledge（字符串数组，每项是一条核心知识的纯文本描述）；"
    "teaching_flow（对象数组，标准行课流程，每项必须包含 step_no（从 1 起的整数）、stage_name（字符串，简短环节名）、"
    "duration_minutes（整数）、teacher_actions（字符串数组，至少 1 条）、student_activities（字符串数组，至少 1 条）、"
    "knowledge_point_refs（输入知识点 id 的整数数组，至少 1 个）；"
    "环节名字段固定使用 stage_name）；"
    "session_plans（对象数组，必须且只能包含 1 个课次安排，对应 target_lesson_session.session_no，"
    "每项必须包含 session_no（整数）、title（字符串）、objectives（字符串数组）、teaching_focus（字符串数组）、"
    "teaching_steps（与 teaching_flow 同结构的对象数组）、homework（字符串数组）、knowledge_point_refs（整数数组））；"
    "after_class_plan（对象，必须且只能包含 review、homework、parent_communication 三个字符串字段，"
    "例如 {\"review\": \"完成基础题 1-3 题并复述...\", \"homework\": \"...\", \"parent_communication\": \"...\"}）；"
    "learner_adjustments（字符串数组，每项是一句策略说明）；"
    "knowledge_point_refs（输入知识点 id 的整数数组）。"
)

_LESSON_PLAN_OUTPUT_RULES_PROMPT = (
    "teaching_flow 和 session_plans 中的 knowledge_point_refs 必须只引用输入中的知识点 id。"
    "教案需覆盖课程概述、物料清单、核心知识、导入、讲解、练习、总结和课后安排。"
    "不得返回空数组或空对象骨架；教师动作、学生活动、课次目标、教学重点、课后任务和学情适配都必须有可执行内容。"
    "不要输出 Markdown、解释文字或代码块。"
)


def _build_lesson_plan_stable_messages(
    *,
    project,
    generation_batch,
    curriculum_plan,
    profile_version,
    knowledge_points: list,
    profile_records: list,
    evidence_images: list[str] | None = None,
) -> list[ChatMessage]:
    """构造教案生成的稳定前缀消息（同一批次跨课次复用）。

    包含 2 条 system（角色与字段定义、硬性输出规则）+ 1 条 user（项目/大纲/知识点/学情
    的 JSON 上下文与可选证据图片）。target_lesson_session 由 _build_lesson_plan_messages
    在循环内追加为第 4 条 user 消息，避免击穿稳定前缀的上游缓存。
    """
    point_payload = [
        {
            "id": point.id,
            "chapter_node_id": point.chapter_node_id,
            "point_name": point.point_name,
            "importance_level": point.importance_level,
            "difficulty_level": point.difficulty_level,
            "mastery_level_hint": point.mastery_level_hint,
            "tags_json": point.tags_json,
            "summary_text": point.summary_text,
        }
        for point in knowledge_points
    ]
    profile_payload = [
        {
            "student_key": record.student_key,
            "student_name": record.student_name,
            "grade_code": record.grade_code,
            "subject_code": record.subject_code,
            "score_value": float(record.score_value) if record.score_value is not None else None,
            "advantage_tags_json": record.advantage_tags_json,
            "weakness_tags_json": record.weakness_tags_json,
            "ability_tags_json": record.ability_tags_json,
            "habit_tags_json": record.habit_tags_json,
            "behavior_traits_json": record.behavior_traits_json,
            "time_plan_json": record.time_plan_json,
            "summary_text": record.summary_text,
        }
        for record in profile_records
    ]
    stable_payload = {
        "project": {
            "id": project.id,
            "name": project.name,
            "subject_code": project.subject_code,
            "grade_code": project.grade_code,
            "applicable_target": project.applicable_target,
            "remark": project.remark,
        },
        "generation_batch": {
            "id": generation_batch.id,
            "batch_no": generation_batch.batch_no,
            "course_count": generation_batch.course_count,
            "session_duration_minutes": generation_batch.session_duration_minutes,
            "chapter_range_json": generation_batch.chapter_range_json,
        },
        "curriculum_plan": {
            "id": curriculum_plan.id,
            "plan_title": curriculum_plan.plan_title,
            "summary_text": curriculum_plan.summary_text,
            "content_json": curriculum_plan.content_json,
        },
        "knowledge_points": point_payload,
        "learner_profile_version": {
            "id": profile_version.id,
            "summary_text": profile_version.summary_text,
            "grade_code": profile_version.grade_code,
            "subject_scope": profile_version.subject_scope,
            "class_profile": (profile_version.raw_result_json or {}).get("class_profile"),
            "records": profile_payload,
        },
    }
    stable_text = json.dumps(stable_payload, ensure_ascii=False)
    if evidence_images:
        stable_user_content: str | list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "以下提供教材中与本课知识点相关的证据插图，请结合图片内容生成更贴合教材的教案。",
            },
            {"type": "text", "text": stable_text},
            *({"type": "image", "data_url": data_url} for data_url in evidence_images),
        ]
    else:
        stable_user_content = stable_text
    return [
        ChatMessage(role="system", content=_LESSON_PLAN_ROLE_AND_SCHEMA_PROMPT),
        ChatMessage(role="system", content=_LESSON_PLAN_OUTPUT_RULES_PROMPT),
        ChatMessage(role="user", content=stable_user_content),
    ]


def _build_lesson_plan_messages(
    *,
    stable_messages: list[ChatMessage],
    target_lesson_session: dict[str, Any],
) -> list[ChatMessage]:
    """组装单次课次的完整请求消息：稳定前缀 + 本课次变量段。

    variable user 消息显式包含 "JSON 对象" 字样，避免 Chat Completions 端再追加兜底
    的纯文本兜底消息，让前 3 条稳定前缀消息成为真正的缓存锚点。
    """
    variable_text = (
        "请基于上述稳定上下文与下方 target_lesson_session 严格以 JSON 对象输出本课次教案：\n"
        + json.dumps({"target_lesson_session": target_lesson_session}, ensure_ascii=False)
    )
    return [*stable_messages, ChatMessage(role="user", content=variable_text)]


def _get_curriculum_lesson_sessions(curriculum_plan) -> list[dict[str, Any]]:
    """从课程大纲中读取按课次拆分的生成计划。"""
    content_json = curriculum_plan.content_json or {}
    lesson_sessions = content_json.get("lesson_sessions") if isinstance(content_json, dict) else None
    if not isinstance(lesson_sessions, list) or not lesson_sessions:
        raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲缺少 lesson_sessions，无法生成教案")

    normalized_sessions: list[dict[str, Any]] = []
    for index, lesson_session in enumerate(lesson_sessions, start=1):
        if not isinstance(lesson_session, dict):
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲课次结构非法")
        session_no = int(lesson_session.get("session_no") or 0)
        if session_no != index:
            raise AppException(
                BusinessErrorCode.GENERATION_BASELINE_INVALID,
                "课程大纲课次序号必须从 1 连续递增",
                {"expected_session_no": index, "actual_session_no": session_no},
            )
        normalized_sessions.append(lesson_session)
    return normalized_sessions


def _validate_lesson_plan_result(
    result: LessonPlanGenerationResult,
    *,
    expected_session_no: int,
    knowledge_point_ids: set[int],
) -> None:
    """校验教案生成结果。"""
    if len(result.session_plans) != 1:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 每次必须只返回一个课次教案",
            {"expected_session_count": 1, "actual_session_count": len(result.session_plans)},
        )
    actual_session_no = result.session_plans[0].session_no
    if actual_session_no != expected_session_no:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回教案课次序号与当前课次不一致",
            {"expected_session_no": expected_session_no, "actual_session_no": actual_session_no},
        )
    invalid_ids = [point_id for point_id in result.knowledge_point_refs if point_id not in knowledge_point_ids]
    for step in result.teaching_flow:
        invalid_ids.extend(point_id for point_id in step.knowledge_point_refs if point_id not in knowledge_point_ids)
    for session_plan in result.session_plans:
        invalid_ids.extend(point_id for point_id in session_plan.knowledge_point_refs if point_id not in knowledge_point_ids)
        for step in session_plan.teaching_steps:
            invalid_ids.extend(point_id for point_id in step.knowledge_point_refs if point_id not in knowledge_point_ids)
    if invalid_ids:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回了不存在的教案知识点引用",
            {"knowledge_point_ids": sorted(set(invalid_ids))},
        )


def _build_lesson_plan_content_json(
    result: LessonPlanGenerationResult,
    *,
    target_lesson_session: dict[str, Any],
) -> dict[str, Any]:
    """构造教案内容 JSON。"""
    return {
        "target_lesson_session": target_lesson_session,
        "course_overview": result.course_overview.model_dump(mode="json"),
        "material_list": result.material_list,
        "core_knowledge": result.core_knowledge,
        "teaching_flow": [step.model_dump(mode="json") for step in result.teaching_flow],
        "session_plans": [session_plan.model_dump(mode="json") for session_plan in result.session_plans],
        "after_class_plan": result.after_class_plan.model_dump(mode="json"),
        "learner_adjustments": result.learner_adjustments,
        "knowledge_point_refs": result.knowledge_point_refs,
    }


def _mark_task(task, *, task_status: str, current_stage: str, progress_percent: int, started_at=None, finished_at=None, result_json: dict | None = None) -> None:
    task.task_status = task_status
    task.current_stage = current_stage
    assign_monotonic_progress(task, progress_percent)
    if started_at is not None:
        task.started_at = task.started_at or started_at
    if finished_at is not None:
        task.finished_at = finished_at
    if result_json is not None:
        task.result_json = result_json


def _mark_step(step, step_status: str, progress_percent: int, *, detail_json: dict | None = None, started_at=None, finished_at=None) -> None:
    step.step_status = step_status
    assign_monotonic_progress(step, progress_percent)
    if detail_json is not None:
        step.detail_json = detail_json
    if started_at is not None:
        step.started_at = step.started_at or started_at
    if finished_at is not None:
        step.finished_at = finished_at


def _get_step_map(task_repository: TaskCenterRepository, task_record_id: int) -> dict[str, object]:
    return {
        step_code: task_repository.get_task_step(task_record_id, step_code)
        for step_code in (
            "prepare_lesson_baseline",
            "invoke_llm_lesson_plan",
            "persist_lesson_plan",
            "finalize_generation_batch",
        )
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: LessonPlanRepository, payload: dict, exc: Exception) -> None:
    """处理教案生成任务失败：可重试错误重排重试，终态失败时级联标记生成批次。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    force_retryable = None
    if isinstance(exc, AppException) and isinstance(exc.details, dict) and exc.details.get("retryable") is False:
        force_retryable = False
    terminal_failed = not requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.LESSON_PLAN_TASK_FAILED,
        force_retryable=force_retryable,
    )
    if terminal_failed:
        _persist_lesson_plan_failure_detail(task_repository, task.id, exc)
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is not None:
            generation_batch.batch_status = TASK_STATUS_FAILURE
            generation_batch.finished_at = DateTimeUtil.now_utc()
            repository.save(generation_batch)
            repository.session.commit()
        _notify_orchestrator_failure(session=repository.session, task=task, exc=exc)


def _persist_lesson_plan_failure_detail(task_repository: TaskCenterRepository, task_id: int, exc: Exception) -> None:
    """终态失败时把课次级安全详情写回教案 LLM 步骤。"""
    if not isinstance(exc, AppException) or not isinstance(exc.details, dict):
        return
    step = task_repository.get_task_step(task_id, "invoke_llm_lesson_plan")
    if step is None:
        return
    step.detail_json = exc.details
    task_repository.save(step)
    task_repository.session.commit()


def _notify_orchestrator_lesson_plan_success(*, session, task) -> None:
    """教案生成成功后通知 orchestrator 更新 run。最终 run 状态由 coverage 推进。"""
    try:
        from app.modules.orchestrator.service import OrchestratorService

        OrchestratorService(session).advance_after_lesson_plan_success(task=task)
    except Exception:  # noqa: BLE001
        import structlog as _structlog

        _structlog.get_logger(__name__).warning("orchestrator lesson_plan hook 调用失败", task_id=task.id, exc_info=True)


def _notify_orchestrator_failure(*, session, task, exc) -> None:
    """终态失败时通知 orchestrator 把 run 标为 failed。"""
    try:
        from app.core.exceptions import AppException as _AppException
        from app.modules.orchestrator.service import OrchestratorService

        error_code = exc.code.value if isinstance(exc, _AppException) else type(exc).__name__
        error_message = exc.message if isinstance(exc, _AppException) else str(exc)
        OrchestratorService(session).mark_run_failed(task=task, error_code=error_code, error_message=error_message)
    except Exception:  # noqa: BLE001
        import structlog as _structlog

        _structlog.get_logger(__name__).warning("orchestrator failure hook 调用失败", task_id=task.id, exc_info=True)


def _create_session(payload: dict) -> Session:
    """为教案生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
