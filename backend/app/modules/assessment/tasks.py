"""
@Date: 2026-05-03
@Author: xisy
@Discription: 测评模块任务执行能力
"""

import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    COURSEWARE_GENERATE_TASK_TYPE,
    COURSEWARE_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    TASK_STATUS_PENDING,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import AssessmentGenerationResult
from app.modules.p0_models import AssessmentBlueprint, PaperResult, QuestionItem
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.queue import dispatch_task
from app.shared.utils import DateTimeUtil

DEFAULT_ASSESSMENT_STRATEGY = {
    "scenario_type": "unit_test",
    "scene_type": "unit_test",
    "question_count": 10,
    "question_types": ["single_choice", "fill_blank", "short_answer"],
    "difficulty_range": [1, 5],
}


def run_generate_assessment_task(payload: dict) -> dict[str, int | str]:
    """执行测评蓝图与试卷生成任务。"""
    session = _create_session(payload)
    repository = AssessmentRepository(session)
    task_repository = TaskCenterRepository(session)
    llm_service = OpenAICompatibleLlmService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()

    try:
        if task is None:
            raise RuntimeError("测评生成任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        curriculum_plan = repository.get_curriculum_plan(payload["curriculum_plan_id"])
        lesson_plan = repository.get_lesson_plan(payload["lesson_plan_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        if curriculum_plan.project_id != generation_batch.project_id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲不属于当前生成批次")
        if lesson_plan.curriculum_plan_id != curriculum_plan.id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案不属于当前课程大纲")
        if generation_batch.curriculum_plan_id != curriculum_plan.id or generation_batch.lesson_plan_id != lesson_plan.id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "生成批次结果引用不完整")

        generation_batch.batch_status = TASK_STATUS_PROCESSING
        generation_batch.started_at = generation_batch.started_at or now
        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_assessment_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_assessment_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        repository.save(generation_batch)
        task_repository.save(task)
        task_repository.save(step_map["prepare_assessment_baseline"])
        session.commit()

        if curriculum_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲版本不可用")
        if lesson_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案版本不可用")
        project = repository.get_project(curriculum_plan.project_id)
        knowledge_points = repository.list_knowledge_points(curriculum_plan.knowledge_version_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        if not knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲绑定的知识版本缺少知识点")

        strategy = _normalize_assessment_strategy(generation_batch.assessment_strategy_json)
        _mark_step(
            step_map["prepare_assessment_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "curriculum_plan_id": curriculum_plan.id,
                "lesson_plan_id": lesson_plan.id,
                "knowledge_version_id": curriculum_plan.knowledge_version_id,
                "knowledge_point_count": len(knowledge_points),
                "assessment_strategy": strategy,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_assessment"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_assessment", progress_percent=40)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        llm_messages = _build_assessment_messages(
            project=project,
            generation_batch=generation_batch,
            curriculum_plan=curriculum_plan,
            lesson_plan=lesson_plan,
            knowledge_points=knowledge_points,
            strategy=strategy,
        )
        generation_result = llm_service.generate_structured_output(
            messages=llm_messages,
            response_model=AssessmentGenerationResult,
        )
        _validate_assessment_result(
            generation_result,
            strategy=strategy,
            knowledge_point_ids={point.id for point in knowledge_points},
        )

        _mark_step(
            step_map["invoke_llm_assessment"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"question_count": len(generation_result.questions)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_assessment_result"], TASK_STATUS_PROCESSING, 45, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_assessment_result", progress_percent=75)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        assessment_blueprint = repository.create_assessment_blueprint(
            AssessmentBlueprint(
                curriculum_plan_id=curriculum_plan.id,
                version_no=repository.get_next_blueprint_version_no(curriculum_plan.id, strategy["scenario_type"]),
                scenario_type=strategy["scenario_type"],
                blueprint_name=generation_result.blueprint_name,
                version_status=VERSION_STATUS_READY,
                strategy_json=strategy,
                content_json=_build_blueprint_content_json(generation_result),
                export_file_id=None,
                created_by=payload.get("operator_user_id"),
            )
        )
        paper_result = repository.create_paper_result(
            PaperResult(
                generation_batch_id=generation_batch.id,
                assessment_blueprint_id=assessment_blueprint.id,
                scene_type=strategy["scene_type"],
                title=generation_result.paper_title,
                result_status=TASK_STATUS_SUCCESS,
                question_count=len(generation_result.questions),
                difficulty_stats_json=_build_difficulty_stats(generation_result),
                paper_json=_build_paper_json(generation_result, strategy=strategy),
                export_file_id=None,
            )
        )
        repository.create_question_items(
            [
                QuestionItem(
                    generation_batch_id=generation_batch.id,
                    paper_result_id=paper_result.id,
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
        generation_batch.assessment_blueprint_id = assessment_blueprint.id

        _mark_step(
            step_map["persist_assessment_result"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "assessment_blueprint_id": assessment_blueprint.id,
                "paper_result_id": paper_result.id,
                "question_count": len(generation_result.questions),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["finalize_generation_batch"], TASK_STATUS_PROCESSING, 70, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_generation_batch", progress_percent=90)
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        courseware_task = _create_courseware_task(
            task_repository=task_repository,
            generation_batch=generation_batch,
            lesson_plan=lesson_plan,
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
                "next_task_id": courseware_task.id,
                "next_task_type": COURSEWARE_GENERATE_TASK_TYPE,
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
                "assessment_blueprint_id": assessment_blueprint.id,
                "paper_result_id": paper_result.id,
                "question_count": len(generation_result.questions),
                "courseware_task_id": courseware_task.id,
            },
            finished_at=finished_at,
        )
        repository.save(generation_batch)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        dispatch_result = dispatch_task(
            "app.modules.courseware.tasks.run_generate_courseware_task",
            {
                "task_record_id": courseware_task.id,
                "generation_batch_id": generation_batch.id,
                "lesson_plan_id": lesson_plan.id,
                "operator_user_id": payload.get("operator_user_id"),
                "database_url": session.get_bind().url.render_as_string(hide_password=False),
            },
        )
        if dispatch_result.worker_task_id:
            courseware_task.worker_task_id = dispatch_result.worker_task_id
            task_repository.save(courseware_task)
            session.commit()
        return {
            "generation_batch_id": generation_batch.id,
            "assessment_blueprint_id": assessment_blueprint.id,
            "paper_result_id": paper_result.id,
            "question_count": len(generation_result.questions),
            "courseware_task_id": courseware_task.id,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _normalize_assessment_strategy(strategy_json: dict[str, Any] | None) -> dict[str, Any]:
    """归一化测评策略。"""
    strategy = {**DEFAULT_ASSESSMENT_STRATEGY, **(strategy_json or {})}
    question_count = int(strategy.get("question_count") or DEFAULT_ASSESSMENT_STRATEGY["question_count"])
    question_types = strategy.get("question_types") or DEFAULT_ASSESSMENT_STRATEGY["question_types"]
    difficulty_range = strategy.get("difficulty_range") or DEFAULT_ASSESSMENT_STRATEGY["difficulty_range"]
    return {
        "scenario_type": str(strategy.get("scenario_type") or "unit_test"),
        "scene_type": str(strategy.get("scene_type") or "unit_test"),
        "question_count": question_count,
        "question_types": [str(question_type) for question_type in question_types],
        "difficulty_range": [int(difficulty_range[0]), int(difficulty_range[1])],
    }


def _build_assessment_messages(
    *,
    project,
    generation_batch,
    curriculum_plan,
    lesson_plan,
    knowledge_points: list,
    strategy: dict[str, Any],
) -> list[ChatMessage]:
    """构造测评生成提示词。"""
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
            "content_json": curriculum_plan.content_json,
        },
        "lesson_plan": {
            "id": lesson_plan.id,
            "lesson_title": lesson_plan.lesson_title,
            "summary_text": lesson_plan.summary_text,
            "content_json": lesson_plan.content_json,
        },
        "knowledge_points": point_payload,
        "assessment_strategy": strategy,
    }
    system_prompt = (
        "你是测评蓝图和试卷生成助手。请基于课程大纲、教案和知识点生成中文单元测试蓝图与题目。"
        "必须严格输出 JSON 对象，字段包含 blueprint_name、paper_title、strategy_summary、"
        "knowledge_weights、question_type_distribution、difficulty_distribution、questions。"
        "questions 数量必须等于 assessment_strategy.question_count，question_no 必须从 1 连续递增。"
        "每道题必须包含 knowledge_point_id、question_type、difficulty_level、stem_text、answer_text、analysis_text。"
        "所有 knowledge_point_id 必须只引用输入中的知识点 id，题型只能使用输入策略中的 question_types。"
        "不要输出 Markdown、解释文字或代码块。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _validate_assessment_result(
    result: AssessmentGenerationResult,
    *,
    strategy: dict[str, Any],
    knowledge_point_ids: set[int],
) -> None:
    """校验测评生成结果。"""
    expected_question_count = int(strategy["question_count"])
    if len(result.questions) != expected_question_count:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回题量不符合测评策略",
            {"expected_question_count": expected_question_count, "actual_question_count": len(result.questions)},
        )
    allowed_question_types = set(strategy["question_types"])
    difficulty_min, difficulty_max = strategy["difficulty_range"]
    invalid_knowledge_ids = [
        item.knowledge_point_id
        for item in result.knowledge_weights
        if item.knowledge_point_id not in knowledge_point_ids
    ]
    invalid_knowledge_ids.extend(
        question.knowledge_point_id
        for question in result.questions
        if question.knowledge_point_id not in knowledge_point_ids
    )
    invalid_question_types = [
        question.question_type
        for question in result.questions
        if question.question_type not in allowed_question_types
    ]
    invalid_difficulties = [
        question.difficulty_level
        for question in result.questions
        if question.difficulty_level < difficulty_min or question.difficulty_level > difficulty_max
    ]
    if invalid_knowledge_ids:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回了不存在的测评知识点引用",
            {"knowledge_point_ids": sorted(set(invalid_knowledge_ids))},
        )
    if invalid_question_types:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回了不符合策略的题型",
            {"question_types": sorted(set(invalid_question_types))},
        )
    if invalid_difficulties:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回了不符合策略的难度等级",
            {"difficulty_levels": sorted(set(invalid_difficulties))},
        )


def _build_blueprint_content_json(result: AssessmentGenerationResult) -> dict[str, Any]:
    """构造测评蓝图内容 JSON。"""
    return {
        "strategy_summary": result.strategy_summary,
        "knowledge_weights": [item.model_dump(mode="json") for item in result.knowledge_weights],
        "question_type_distribution": result.question_type_distribution,
        "difficulty_distribution": result.difficulty_distribution,
    }


def _build_paper_json(result: AssessmentGenerationResult, *, strategy: dict[str, Any]) -> dict[str, Any]:
    """构造试卷内容 JSON。"""
    return {
        "paper_title": result.paper_title,
        "scene_type": strategy["scene_type"],
        "question_type_distribution": result.question_type_distribution,
        "difficulty_distribution": result.difficulty_distribution,
        "questions": [question.model_dump(mode="json") for question in result.questions],
    }


def _build_difficulty_stats(result: AssessmentGenerationResult) -> dict[str, Any]:
    """构造难度统计。"""
    if result.difficulty_distribution:
        return result.difficulty_distribution
    stats: dict[str, int] = {}
    for question in result.questions:
        key = str(question.difficulty_level)
        stats[key] = stats.get(key, 0) + 1
    return stats


def _create_courseware_task(
    *,
    task_repository: TaskCenterRepository,
    generation_batch,
    lesson_plan,
    owner_user_id: int | None,
    request_id: str | None,
):
    """创建课件生成任务。"""
    task = task_repository.create_task(
        project_id=generation_batch.project_id,
        generation_batch_id=generation_batch.id,
        module_code=COURSEWARE_MODULE_CODE,
        task_type=COURSEWARE_GENERATE_TASK_TYPE,
        task_status=TASK_STATUS_PENDING,
        queue_name=GENERATION_QUEUE_NAME,
        biz_key=f"generation_batch:{generation_batch.id}:courseware",
        operator_user_id=owner_user_id,
        payload_json={
            "generation_batch_id": generation_batch.id,
            "lesson_plan_id": lesson_plan.id,
        },
        request_id=request_id,
    )
    step_names = [
        ("prepare_courseware_baseline", "准备课件生成基线"),
        ("create_raccoon_ppt_job", "创建 Raccoon PPT 任务"),
        ("poll_raccoon_ppt_job", "轮询 Raccoon PPT 任务"),
        ("archive_courseware_result", "归档课件 PPTX"),
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
            "prepare_assessment_baseline",
            "invoke_llm_assessment",
            "persist_assessment_result",
            "finalize_generation_batch",
        )
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: AssessmentRepository, payload: dict, exc: Exception) -> None:
    task = task_repository.get_task_by_id(payload["task_record_id"])
    generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
    if generation_batch is not None:
        generation_batch.batch_status = TASK_STATUS_FAILURE
        generation_batch.finished_at = DateTimeUtil.now_utc()
        repository.save(generation_batch)
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = getattr(exc, "code", None).value if isinstance(exc, AppException) else "ASSESSMENT_TASK_FAILED"
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)
    for step_code in (
        "prepare_assessment_baseline",
        "invoke_llm_assessment",
        "persist_assessment_result",
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
    """为测评生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
