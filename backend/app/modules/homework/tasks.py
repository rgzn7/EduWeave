"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业生成任务执行能力，按课次维度产出蓝图、作业和题目
"""

import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.assessment._shared import (
    build_blueprint_content_json,
    build_difficulty_stats,
    build_paper_content_json,
    normalize_assessment_distributions,
    truncate_questions_to_strategy,
    validate_assessment_result,
)
from app.modules.assessment.schemas import AssessmentGenerationResult
from app.modules.coverage.service import CoverageService
from app.modules.homework.presets import resolve_homework_strategy
from app.modules.homework.repository import HomeworkRepository
from app.modules.p0_models import HomeworkBlueprint, HomeworkQuestion, HomeworkResult
from app.modules.task_center.recovery import requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.utils import DateTimeUtil
from app.shared.utils.chapter_range_util import build_chapter_range_selection, filter_knowledge_points_by_chapter_selection

LESSON_KNOWLEDGE_REF_KEYS = {
    "knowledge_point_id",
    "knowledge_point_ids",
    "knowledge_point_refs",
    "coverage_knowledge_points",
}


def run_generate_homework_task(payload: dict) -> dict[str, int | str]:
    """执行单课次课后作业生成任务。"""
    session = _create_session(payload)
    repository = HomeworkRepository(session)
    task_repository = TaskCenterRepository(session)
    llm_service = OpenAICompatibleLlmService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "课后作业生成任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        lesson_plan = repository.get_lesson_plan(payload["lesson_plan_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        if lesson_plan.generation_batch_id != generation_batch.id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案不属于当前生成批次")
        curriculum_plan = repository.get_curriculum_plan(lesson_plan.curriculum_plan_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")

        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_homework_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_homework_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_homework_baseline"])
        session.commit()

        if lesson_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案版本不可用")
        project = repository.get_project(curriculum_plan.project_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        all_knowledge_points = repository.list_knowledge_points(generation_batch.knowledge_version_id)
        if not all_knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲绑定的知识版本缺少知识点")
        chapters = repository.list_chapter_nodes(generation_batch.knowledge_version_id)
        chapter_selection = build_chapter_range_selection(
            chapters=chapters,
            chapter_range_json=generation_batch.chapter_range_json,
        )
        scoped_points = filter_knowledge_points_by_chapter_selection(
            knowledge_points=all_knowledge_points,
            selection=chapter_selection,
        )
        lesson_knowledge_points = _resolve_lesson_knowledge_points(
            lesson_plan=lesson_plan,
            scoped_points=scoped_points,
        )
        knowledge_point_ids = {point.id for point in lesson_knowledge_points}

        strategy = resolve_homework_strategy()
        _mark_step(
            step_map["prepare_homework_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "lesson_plan_id": lesson_plan.id,
                "class_session_no": lesson_plan.class_session_no,
                "knowledge_version_id": curriculum_plan.knowledge_version_id,
                "chapter_range_scoped": chapter_selection.is_scoped,
                "scoped_knowledge_point_count": len(scoped_points),
                "lesson_knowledge_point_count": len(lesson_knowledge_points),
                "homework_strategy": strategy,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_homework"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_homework", progress_percent=40)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        llm_messages = _build_homework_messages(
            project=project,
            generation_batch=generation_batch,
            curriculum_plan=curriculum_plan,
            lesson_plan=lesson_plan,
            knowledge_points=lesson_knowledge_points,
            strategy=strategy,
        )
        generation_result = llm_service.generate_structured_output(
            messages=llm_messages,
            response_model=AssessmentGenerationResult,
        )
        truncate_questions_to_strategy(generation_result, expected_question_count=int(strategy["question_count"]))
        validate_assessment_result(
            generation_result,
            strategy=strategy,
            knowledge_point_ids=knowledge_point_ids,
        )
        normalize_assessment_distributions(generation_result)

        _mark_step(
            step_map["invoke_llm_homework"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"question_count": len(generation_result.questions)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_homework_result"], TASK_STATUS_PROCESSING, 45, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_homework_result", progress_percent=75)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        homework_blueprint = repository.create_homework_blueprint(
            HomeworkBlueprint(
                lesson_plan_id=lesson_plan.id,
                generation_batch_id=generation_batch.id,
                version_no=repository.get_next_homework_blueprint_version_no(lesson_plan.id),
                blueprint_name=generation_result.blueprint_name,
                version_status=VERSION_STATUS_READY,
                strategy_json=strategy,
                content_json=build_blueprint_content_json(generation_result),
                export_file_id=None,
                created_by=payload.get("operator_user_id"),
            )
        )
        homework_result = repository.create_homework_result(
            HomeworkResult(
                generation_batch_id=generation_batch.id,
                lesson_plan_id=lesson_plan.id,
                homework_blueprint_id=homework_blueprint.id,
                title=generation_result.paper_title,
                result_status=TASK_STATUS_SUCCESS,
                question_count=len(generation_result.questions),
                difficulty_stats_json=build_difficulty_stats(generation_result),
                content_json=build_paper_content_json(generation_result, strategy=strategy),
                export_file_id=None,
            )
        )
        repository.create_homework_questions(
            [
                HomeworkQuestion(
                    generation_batch_id=generation_batch.id,
                    homework_result_id=homework_result.id,
                    lesson_plan_id=lesson_plan.id,
                    knowledge_point_id=question.knowledge_point_id,
                    question_no=question.question_no,
                    question_type=question.question_type,
                    difficulty_level=question.difficulty_level,
                    score_value=question.score_value,
                    stem_text=question.stem_text,
                    options_json=question.options_json,
                    answer_text=question.answer_text,
                    analysis_text=question.analysis_text,
                    source_trace_json=question.source_trace_json,
                )
                for question in generation_result.questions
            ]
        )
        CoverageService(session).refresh_coverage_report_by_batch(generation_batch.id)
        _mark_step(
            step_map["persist_homework_result"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "homework_blueprint_id": homework_blueprint.id,
                "homework_result_id": homework_result.id,
                "question_count": len(generation_result.questions),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["finalize_homework_task"], TASK_STATUS_PROCESSING, 70, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_homework_task", progress_percent=90)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        finished_at = DateTimeUtil.now_utc()
        _mark_step(
            step_map["finalize_homework_task"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"homework_blueprint_id": homework_blueprint.id, "homework_result_id": homework_result.id},
            finished_at=finished_at,
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="finalize_homework_task",
            progress_percent=100,
            result_json={
                "generation_batch_id": generation_batch.id,
                "lesson_plan_id": lesson_plan.id,
                "homework_blueprint_id": homework_blueprint.id,
                "homework_result_id": homework_result.id,
                "question_count": len(generation_result.questions),
            },
            finished_at=finished_at,
        )
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        return {
            "generation_batch_id": generation_batch.id,
            "lesson_plan_id": lesson_plan.id,
            "homework_blueprint_id": homework_blueprint.id,
            "homework_result_id": homework_result.id,
            "question_count": len(generation_result.questions),
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, payload, exc)
        raise
    finally:
        session.close()


def _build_homework_messages(
    *,
    project,
    generation_batch,
    curriculum_plan,
    lesson_plan,
    knowledge_points: list,
    strategy: dict[str, Any],
) -> list[ChatMessage]:
    """构造课后作业生成提示词。"""
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
    user_payload = {
        "project": {
            "id": project.id,
            "name": project.name,
            "subject_code": project.subject_code,
            "grade_code": project.grade_code,
            "applicable_target": project.applicable_target,
        },
        "generation_batch": {
            "id": generation_batch.id,
            "batch_no": generation_batch.batch_no,
            "chapter_range_json": generation_batch.chapter_range_json,
        },
        "curriculum_plan": {
            "id": curriculum_plan.id,
            "plan_title": curriculum_plan.plan_title,
            "summary_text": curriculum_plan.summary_text,
        },
        "lesson_plan": {
            "id": lesson_plan.id,
            "class_session_no": lesson_plan.class_session_no,
            "lesson_title": lesson_plan.lesson_title,
            "summary_text": lesson_plan.summary_text,
            "content_json": lesson_plan.content_json,
        },
        "knowledge_points": point_payload,
        "assessment_strategy": strategy,
    }
    scene_label = str(strategy.get("scene_label") or "课后作业")
    prompt_constraint = str(strategy.get("prompt_constraint") or "")
    system_prompt = (
        "你是课后作业生成助手。"
        f"当前任务是为单节课（class_session_no={lesson_plan.class_session_no}，lesson_title={lesson_plan.lesson_title}）"
        f"生成{scene_label}（scene_type=homework）。"
        f"{prompt_constraint}"
        "题目必须紧扣本课教案的教学目标、教学内容与本课知识点，不要扩展到其它课次或单元。"
        "必须严格输出 JSON 对象，字段包含 blueprint_name、paper_title、strategy_summary、"
        "knowledge_weights、question_type_distribution、difficulty_distribution、questions。"
        "blueprint_name 与 paper_title 必须体现本课标题，例如以教案标题或课次序号开头。"
        "questions 数量必须不少于 assessment_strategy.question_count，只能多不能少；"
        "如不确定可适当多出几道，多余题目会按题号顺序被截断，但绝不允许少于该题量。"
        "question_no 必须从 1 开始连续递增且不得重复。"
        "每道题的 difficulty_level 必须落在 assessment_strategy.difficulty_range 指定的闭区间内。"
        "question_type_distribution 和 difficulty_distribution 必须与 questions 逐题统计完全一致。"
        "每道题必须包含 knowledge_point_id、question_type、difficulty_level、stem_text、answer_text、analysis_text。"
        "所有 knowledge_point_id 必须只引用输入 knowledge_points 中的 id，题型只能使用输入策略中的 question_types。"
        "不要输出 Markdown、解释文字或代码块。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _resolve_lesson_knowledge_points(*, lesson_plan, scoped_points: list) -> list:
    """从教案 content_json 抽取本课知识点引用，回退到批次范围内全部知识点。"""
    referenced_ids = _extract_lesson_knowledge_point_ids(lesson_plan.content_json)
    if not referenced_ids:
        return scoped_points
    referenced_set = set(referenced_ids)
    lesson_points = [point for point in scoped_points if point.id in referenced_set]
    return lesson_points or scoped_points


def _extract_lesson_knowledge_point_ids(payload: Any) -> list[int]:
    """递归提取教案中的知识点引用 id。"""
    result: list[int] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in LESSON_KNOWLEDGE_REF_KEYS:
                result.extend(_normalize_id_values(value))
            else:
                result.extend(_extract_lesson_knowledge_point_ids(value))
    elif isinstance(payload, list):
        for item in payload:
            result.extend(_extract_lesson_knowledge_point_ids(item))
    return result


def _normalize_id_values(value: Any) -> list[int]:
    """将知识点引用字段归一为整数列表。"""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdigit():
        return [int(value)]
    if isinstance(value, list):
        ids: list[int] = []
        for item in value:
            ids.extend(_normalize_id_values(item))
        return ids
    return []


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


def _get_step_map(task_repository: TaskCenterRepository, task_record_id: int) -> dict[str, object]:
    return {
        step_code: task_repository.get_task_step(task_record_id, step_code)
        for step_code in (
            "prepare_homework_baseline",
            "invoke_llm_homework",
            "persist_homework_result",
            "finalize_homework_task",
        )
    }


def _mark_task_failure(task_repository: TaskCenterRepository, payload: dict, exc: Exception) -> None:
    """处理作业生成任务失败：可重试错误重排重试，否则判终态失败。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.HOMEWORK_TASK_FAILED,
    )


def _create_session(payload: dict) -> Session:
    """为作业生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
