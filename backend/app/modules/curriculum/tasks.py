"""
@Date: 2026-05-04
@Author: xisy
@Discription: 课程大纲模块任务执行能力
"""

import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    GENERATION_QUEUE_NAME,
    LESSON_PLAN_GENERATE_TASK_TYPE,
    LESSON_PLAN_MODULE_CODE,
    TASK_STATUS_PENDING,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode, get_task_error_code
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.p0_models import CurriculumPlan
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.queue import dispatch_task
from app.shared.utils import DateTimeUtil
from app.shared.utils.chapter_range_util import build_chapter_range_selection, filter_knowledge_points_by_chapter_selection


def run_generate_curriculum_task(payload: dict) -> dict[str, int | str]:
    """执行课程大纲生成任务。"""
    session = _create_session(payload)
    repository = CurriculumRepository(session)
    task_repository = TaskCenterRepository(session)
    llm_service = OpenAICompatibleLlmService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()
    curriculum_task_completed = False

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "课程大纲生成任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")

        generation_batch.batch_status = TASK_STATUS_PROCESSING
        generation_batch.started_at = generation_batch.started_at or now
        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_generation_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_generation_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        repository.save(generation_batch)
        task_repository.save(task)
        task_repository.save(step_map["prepare_generation_baseline"])
        session.commit()

        project = repository.get_project(generation_batch.project_id)
        knowledge_version = repository.get_knowledge_version(generation_batch.knowledge_version_id)
        profile_version = repository.get_learner_profile_version(generation_batch.learner_profile_version_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        if knowledge_version is None or knowledge_version.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "知识版本不存在或不可用")
        if (
            profile_version is None
            or profile_version.version_status != VERSION_STATUS_READY
            or profile_version.extract_status != "success"
        ):
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "学情版本不存在或不可用")

        chapters = repository.list_chapter_nodes(knowledge_version.id)
        knowledge_points = repository.list_knowledge_points(knowledge_version.id)
        profile_records = repository.list_profile_records(profile_version.id)
        if not chapters or not knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "知识版本缺少章节或知识点")
        if not profile_records:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "学情版本缺少画像记录")
        chapter_selection = build_chapter_range_selection(
            chapters=chapters,
            chapter_range_json=generation_batch.chapter_range_json,
        )
        scoped_chapters = chapter_selection.chapters
        scoped_knowledge_points = filter_knowledge_points_by_chapter_selection(
            knowledge_points=knowledge_points,
            selection=chapter_selection,
        )

        _mark_step(
            step_map["prepare_generation_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "knowledge_version_id": knowledge_version.id,
                "learner_profile_version_id": profile_version.id,
                "chapter_count": len(scoped_chapters),
                "knowledge_point_count": len(scoped_knowledge_points),
                "chapter_range_scoped": chapter_selection.is_scoped,
                "requested_chapter_ids": chapter_selection.requested_chapter_ids,
                "effective_chapter_ids": chapter_selection.effective_chapter_ids,
                "profile_record_count": len(profile_records),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_curriculum"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_curriculum", progress_percent=40)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        llm_messages = _build_curriculum_messages(
            project=project,
            generation_batch=generation_batch,
            knowledge_version=knowledge_version,
            profile_version=profile_version,
            chapters=scoped_chapters,
            knowledge_points=scoped_knowledge_points,
            profile_records=profile_records,
            chapter_range_scope={
                "is_scoped": chapter_selection.is_scoped,
                "requested_chapter_ids": chapter_selection.requested_chapter_ids,
                "effective_chapter_ids": chapter_selection.effective_chapter_ids,
            },
        )
        generation_result = llm_service.generate_structured_output(
            messages=llm_messages,
            response_model=CurriculumGenerationResult,
        )
        _validate_curriculum_result(
            generation_result,
            course_count=int(generation_batch.course_count or 0),
            knowledge_point_ids={point.id for point in scoped_knowledge_points},
        )

        _mark_step(
            step_map["invoke_llm_curriculum"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"session_count": len(generation_result.lesson_sessions)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_curriculum_plan"], TASK_STATUS_PROCESSING, 45, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_curriculum_plan", progress_percent=75)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        target_record = _pick_target_profile_record(profile_records, project.subject_code)
        curriculum_plan = repository.create_curriculum_plan(
            CurriculumPlan(
                project_id=generation_batch.project_id,
                knowledge_version_id=knowledge_version.id,
                learner_profile_version_id=profile_version.id,
                parent_plan_id=None,
                version_no=repository.get_next_curriculum_version_no(generation_batch.project_id),
                plan_title=generation_result.plan_title,
                target_subject_code=target_record.subject_code if target_record is not None else project.subject_code,
                target_grade_code=(
                    target_record.grade_code
                    if target_record is not None and target_record.grade_code
                    else profile_version.grade_code or project.grade_code
                ),
                chapter_range_json=generation_batch.chapter_range_json,
                course_count=int(generation_batch.course_count or 0),
                session_duration_minutes=int(generation_batch.session_duration_minutes or 0),
                generation_mode="ai",
                version_status=VERSION_STATUS_READY,
                summary_text=generation_result.summary_text,
                content_json=_build_curriculum_content_json(generation_result),
                export_file_id=None,
                created_by=payload.get("operator_user_id"),
            )
        )
        generation_batch.curriculum_plan_id = curriculum_plan.id

        _mark_step(
            step_map["persist_curriculum_plan"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"curriculum_plan_id": curriculum_plan.id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["finalize_generation_batch"], TASK_STATUS_PROCESSING, 70, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_generation_batch", progress_percent=90)
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        lesson_task = _create_lesson_plan_task(
            task_repository=task_repository,
            generation_batch=generation_batch,
            curriculum_plan=curriculum_plan,
            owner_user_id=payload.get("operator_user_id"),
            request_id=task.request_id,
        )
        finished_at = DateTimeUtil.now_utc()
        generation_batch.batch_status = TASK_STATUS_PROCESSING
        _mark_step(
            step_map["finalize_generation_batch"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "batch_status": TASK_STATUS_PROCESSING,
                "next_task_id": lesson_task.id,
                "next_task_type": LESSON_PLAN_GENERATE_TASK_TYPE,
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
                "lesson_plan_task_id": lesson_task.id,
            },
            finished_at=finished_at,
        )
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        curriculum_task_completed = True

        dispatch_result = dispatch_task(
            "app.modules.lesson_plan.tasks.run_generate_lesson_plan_task",
            {
                "task_record_id": lesson_task.id,
                "generation_batch_id": generation_batch.id,
                "curriculum_plan_id": curriculum_plan.id,
                "operator_user_id": payload.get("operator_user_id"),
                "database_url": session.get_bind().url.render_as_string(hide_password=False),
            },
            queue=GENERATION_QUEUE_NAME,
        )
        if dispatch_result.worker_task_id:
            lesson_task.worker_task_id = dispatch_result.worker_task_id
            task_repository.save(lesson_task)
            session.commit()
        return {
            "generation_batch_id": generation_batch.id,
            "curriculum_plan_id": curriculum_plan.id,
            "lesson_plan_task_id": lesson_task.id,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        if not curriculum_task_completed:
            _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _build_curriculum_messages(
    *,
    project,
    generation_batch,
    knowledge_version,
    profile_version,
    chapters: list,
    knowledge_points: list,
    profile_records: list,
    chapter_range_scope: dict[str, Any],
) -> list[ChatMessage]:
    """构造课程大纲生成提示词。"""
    chapter_payload = [
        {
            "id": chapter.id,
            "node_path": chapter.node_path,
            "node_level": chapter.node_level,
            "title": chapter.title,
            "summary_text": chapter.summary_text,
            "page_start": chapter.page_start,
            "page_end": chapter.page_end,
        }
        for chapter in chapters
    ]
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
    user_payload = {
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
        "knowledge_version": {
            "id": knowledge_version.id,
            "summary_json": knowledge_version.summary_json,
            "chapter_range_scope": chapter_range_scope,
            "chapters": chapter_payload,
            "knowledge_points": point_payload,
        },
        "learner_profile_version": {
            "id": profile_version.id,
            "summary_text": profile_version.summary_text,
            "grade_code": profile_version.grade_code,
            "subject_scope": profile_version.subject_scope,
            "records": profile_payload,
        },
    }
    system_prompt = (
        "你是课程大纲生成助手。请基于教材知识结构和学生学情生成中文课程大纲。"
        "若 generation_batch.chapter_range_json 指定了章节范围，输入的教材章节和知识点已经被收敛到该范围，"
        "必须只围绕该局部范围规划课程。"
        "必须严格输出 JSON 对象，字段如下，类型必须严格匹配，不允许嵌套替换："
        "plan_title（字符串，不超过 255 字）；"
        "summary_text（字符串）；"
        "course_overview（对象，可包含 audience、duration、focus 等键，禁止使用字符串或数组）；"
        "stage_goals（字符串数组，每项是一句简短目标，例如 \"激活已有词汇\"，禁止使用对象）；"
        "lesson_sessions（对象数组，每项必须包含 session_no（整数，从 1 连续递增）、title（字符串）、"
        "duration_minutes（整数）、objectives（字符串数组）、key_points（字符串数组）、"
        "activities（字符串数组）、homework（字符串数组）、knowledge_point_refs（输入知识点 id 的整数数组））；"
        "key_points 和 difficult_points（字符串数组）；"
        "learner_adjustments（字符串数组）；"
        "coverage_knowledge_points（输入知识点 id 的整数数组）。"
        "lesson_sessions 数量必须等于 course_count，session_no 必须从 1 连续递增。"
        "coverage_knowledge_points 和每个 lesson_sessions.knowledge_point_refs 必须只引用输入中的知识点 id。"
        "不要输出 Markdown、解释文字或代码块。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _validate_curriculum_result(
    result: CurriculumGenerationResult,
    *,
    course_count: int,
    knowledge_point_ids: set[int],
) -> None:
    """校验课程大纲生成结果。"""
    session_nos = [session.session_no for session in result.lesson_sessions]
    expected_session_nos = list(range(1, course_count + 1))
    if session_nos != expected_session_nos:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回课次数量或序号不符合课程配置",
            {"expected_session_nos": expected_session_nos, "actual_session_nos": session_nos},
        )
    invalid_coverage_ids = [point_id for point_id in result.coverage_knowledge_points if point_id not in knowledge_point_ids]
    if invalid_coverage_ids:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回了不存在的覆盖知识点",
            {"knowledge_point_ids": invalid_coverage_ids},
        )
    for session in result.lesson_sessions:
        invalid_ref_ids = [point_id for point_id in session.knowledge_point_refs if point_id not in knowledge_point_ids]
        if invalid_ref_ids:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回了不存在的课次知识点引用",
                {"session_no": session.session_no, "knowledge_point_ids": invalid_ref_ids},
            )


def _build_curriculum_content_json(result: CurriculumGenerationResult) -> dict[str, Any]:
    """构造课程大纲内容 JSON。"""
    return {
        "course_overview": result.course_overview,
        "stage_goals": result.stage_goals,
        "lesson_sessions": [session.model_dump(mode="json") for session in result.lesson_sessions],
        "key_points": result.key_points,
        "difficult_points": result.difficult_points,
        "learner_adjustments": result.learner_adjustments,
        "coverage_knowledge_points": result.coverage_knowledge_points,
    }


def _pick_target_profile_record(profile_records: list, subject_code: str):
    """优先选择与项目学科一致的学情记录。"""
    for record in profile_records:
        if record.subject_code == subject_code:
            return record
    return profile_records[0] if profile_records else None


def _create_lesson_plan_task(
    *,
    task_repository: TaskCenterRepository,
    generation_batch,
    curriculum_plan,
    owner_user_id: int | None,
    request_id: str | None,
):
    """创建教案生成任务。"""
    task = task_repository.create_task(
        project_id=generation_batch.project_id,
        generation_batch_id=generation_batch.id,
        module_code=LESSON_PLAN_MODULE_CODE,
        task_type=LESSON_PLAN_GENERATE_TASK_TYPE,
        task_status=TASK_STATUS_PENDING,
        queue_name=GENERATION_QUEUE_NAME,
        biz_key=f"generation_batch:{generation_batch.id}:lesson_plan",
        operator_user_id=owner_user_id,
        payload_json={
            "generation_batch_id": generation_batch.id,
            "curriculum_plan_id": curriculum_plan.id,
        },
        request_id=request_id,
    )
    step_names = [
        ("prepare_lesson_baseline", "准备教案生成基线"),
        ("invoke_llm_lesson_plan", "调用 LLM 生成教案"),
        ("persist_lesson_plan", "落库教案"),
        ("finalize_generation_batch", "完成生成批次"),
    ]
    for step_order, (step_code, step_name) in enumerate(step_names, start=1):
        task_repository.create_task_step(
            task_record_id=task.id,
            step_code=step_code,
            step_name=step_name,
            step_order=step_order,
            step_status=TASK_STATUS_PENDING,
        )
    return task


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
            "prepare_generation_baseline",
            "invoke_llm_curriculum",
            "persist_curriculum_plan",
            "finalize_generation_batch",
        )
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: CurriculumRepository, payload: dict, exc: Exception) -> None:
    task = task_repository.get_task_by_id(payload["task_record_id"])
    generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
    if generation_batch is not None:
        generation_batch.batch_status = TASK_STATUS_FAILURE
        generation_batch.finished_at = DateTimeUtil.now_utc()
        repository.save(generation_batch)
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = get_task_error_code(exc, BusinessErrorCode.CURRICULUM_TASK_FAILED)
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)
    for step_code in (
        "prepare_generation_baseline",
        "invoke_llm_curriculum",
        "persist_curriculum_plan",
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
    """为课程大纲生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
