"""
@Date: 2026-05-04
@Author: xisy
@Discription: 教案模块任务执行能力
"""

import json
from typing import Any

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.constants import (
    COVERAGE_ANALYZE_TASK_TYPE,
    GENERATION_QUEUE_NAME,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.coverage.service import CoverageService
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.modules.p0_models import LessonPlan
from app.modules.task_center.heartbeat import (
    StaleAttemptError,
    TaskHeartbeat,
    dispatch_with_attempt,
    ensure_attempt,
)
from app.modules.task_center.recovery import requeue_or_fail_task
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
        _mark_step(step_map["invoke_llm_lesson_plan"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
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
        usage_records: list[LlmUsage] = []

        lesson_plan_ids: list[int] = []
        next_version_no = repository.get_next_lesson_plan_version_no(curriculum_plan.id)
        total_sessions = len(lesson_sessions)
        for index, lesson_session in enumerate(lesson_sessions, start=1):
            class_session_no = int(lesson_session["session_no"])
            # 每节课调用 LLM 前先 touch，长生成不被 reaper 误判
            heartbeat.touch()
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
            )
            _validate_lesson_plan_result(
                generation_result,
                expected_session_no=class_session_no,
                knowledge_point_ids={point.id for point in knowledge_points},
            )
            # 当节 LLM 完成 → 推进任务 progress，并刷新 step 计数
            chunk_progress = 30 + int(45 * index / max(total_sessions, 1))
            heartbeat.tick(progress_percent=chunk_progress, current_stage="invoke_llm_lesson_plan")
            heartbeat.update_step_detail(
                step_id=step_map["invoke_llm_lesson_plan"].id,
                progress_percent=int(100 * index / max(total_sessions, 1)),
                detail_json={
                    "processed_sessions": index,
                    "total_sessions": total_sessions,
                    "class_session_no": class_session_no,
                },
            )
            lesson_plan = repository.create_lesson_plan(
                LessonPlan(
                    curriculum_plan_id=curriculum_plan.id,
                    generation_batch_id=generation_batch.id,
                    class_session_no=class_session_no,
                    version_no=next_version_no + index - 1,
                    lesson_title=generation_result.lesson_title,
                    style_code="standard",
                    version_status=VERSION_STATUS_READY,
                    summary_text=generation_result.summary_text,
                    content_json=_build_lesson_plan_content_json(
                        generation_result,
                        target_lesson_session=lesson_session,
                    ),
                    export_file_id=None,
                    created_by=payload.get("operator_user_id"),
                )
            )
            lesson_plan_ids.append(lesson_plan.id)

        generation_batch.lesson_plan_id = lesson_plan_ids[0]
        _mark_step(
            step_map["invoke_llm_lesson_plan"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "lesson_plan_count": len(lesson_plan_ids),
                "lesson_plan_ids": lesson_plan_ids,
                "llm_usage": _summarize_llm_usage(usage_records),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_lesson_plan"], TASK_STATUS_PROCESSING, 45, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_lesson_plan", progress_percent=75)
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
                callable_path="app.modules.coverage.tasks.run_analyze_coverage_task",
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
    "你是教案生成助手。请基于课程大纲中的 target_lesson_session、教材知识点和学生学情生成中文教师教案。"
    "必须严格输出 JSON 对象，字段如下，类型必须严格匹配，不允许将字符串字段替换为对象或数组："
    "lesson_title（字符串，不超过 255 字）；"
    "summary_text（字符串）；"
    "course_overview（对象，可包含 audience、duration、focus 等键，禁止使用字符串或数组）；"
    "material_list（字符串数组，每项是一句简述，例如 \"单词卡片若干\"）；"
    "core_knowledge（字符串数组，每项是一条核心知识的纯文本描述，禁止使用对象）；"
    "teaching_flow（对象数组，标准行课流程，每项必须包含 step_no（从 1 起的整数）、stage_name（字符串，简短环节名）、"
    "duration_minutes（整数）、teacher_actions（字符串数组，至少 1 条）、student_activities（字符串数组，至少 1 条）、"
    "knowledge_point_refs（输入知识点 id 的整数数组，至少 1 个），不要使用 stage 字段替代 stage_name）；"
    "session_plans（对象数组，必须且只能包含 1 个课次安排，对应 target_lesson_session.session_no，"
    "每项必须包含 session_no（整数）、title（字符串）、objectives（字符串数组）、teaching_focus（字符串数组）、"
    "teaching_steps（与 teaching_flow 同结构的对象数组）、homework（字符串数组）、knowledge_point_refs（整数数组））；"
    "after_class_plan（对象，可包含 review、homework、parent_communication 等键，禁止使用字符串或数组）；"
    "learner_adjustments（字符串数组，每项是一句策略说明，禁止使用对象）；"
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
        "course_overview": result.course_overview,
        "material_list": result.material_list,
        "core_knowledge": result.core_knowledge,
        "teaching_flow": [step.model_dump(mode="json") for step in result.teaching_flow],
        "session_plans": [session_plan.model_dump(mode="json") for session_plan in result.session_plans],
        "after_class_plan": result.after_class_plan,
        "learner_adjustments": result.learner_adjustments,
        "knowledge_point_refs": result.knowledge_point_refs,
    }


def _mark_task(task, *, task_status: str, current_stage: str, progress_percent: int, started_at=None, finished_at=None, result_json: dict | None = None) -> None:
    task.task_status = task_status
    task.current_stage = current_stage
    task.progress_percent = progress_percent
    if started_at is not None:
        task.started_at = task.started_at or started_at
    if finished_at is not None:
        task.finished_at = finished_at
    if result_json is not None:
        task.result_json = result_json


def _mark_step(step, step_status: str, progress_percent: int, *, detail_json: dict | None = None, started_at=None, finished_at=None) -> None:
    step.step_status = step_status
    step.progress_percent = progress_percent
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
    terminal_failed = not requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.LESSON_PLAN_TASK_FAILED,
    )
    if terminal_failed:
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is not None:
            generation_batch.batch_status = TASK_STATUS_FAILURE
            generation_batch.finished_at = DateTimeUtil.now_utc()
            repository.save(generation_batch)
            repository.session.commit()
        _notify_orchestrator_failure(session=repository.session, task=task, exc=exc)


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
