"""
@Date: 2026-05-04
@Author: xisy
@Discription: 测评模块任务执行能力
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
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import AssessmentGenerationResult, AssessmentKnowledgeWeightDraft
from app.modules.p0_models import AssessmentBlueprint, PaperResult, QuestionItem
from app.modules.task_center.recovery import requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.utils import DateTimeUtil
from app.shared.utils.chapter_range_util import build_chapter_range_selection, filter_knowledge_points_by_chapter_selection

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
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "测评生成任务不存在")
        generation_batch = repository.get_generation_batch(payload["generation_batch_id"])
        curriculum_plan = repository.get_curriculum_plan(payload["curriculum_plan_id"])
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        if curriculum_plan.project_id != generation_batch.project_id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲不属于当前生成批次")
        if generation_batch.curriculum_plan_id != curriculum_plan.id:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "生成批次结果引用不完整")

        _mark_task(
            task,
            task_status=TASK_STATUS_PROCESSING,
            current_stage="prepare_assessment_baseline",
            progress_percent=10,
            started_at=now,
        )
        _mark_step(step_map["prepare_assessment_baseline"], TASK_STATUS_PROCESSING, 20, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_assessment_baseline"])
        session.commit()

        if curriculum_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲版本不可用")
        project = repository.get_project(curriculum_plan.project_id)
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
        lesson_plans = repository.list_lesson_plans_by_batch(generation_batch.id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        if not all_knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "课程大纲绑定的知识版本缺少知识点")
        if not lesson_plans:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "测评生成前必须先完成至少一份教案")

        strategy = _normalize_assessment_strategy(
            payload.get("assessment_strategy_json") or generation_batch.assessment_strategy_json
        )
        _mark_step(
            step_map["prepare_assessment_baseline"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "curriculum_plan_id": curriculum_plan.id,
                "knowledge_version_id": curriculum_plan.knowledge_version_id,
                "chapter_range_scoped": chapter_selection.is_scoped,
                "requested_chapter_ids": chapter_selection.requested_chapter_ids,
                "effective_chapter_ids": chapter_selection.effective_chapter_ids,
                "total_knowledge_version_point_count": len(all_knowledge_points),
                "knowledge_point_count": len(knowledge_points),
                "lesson_plan_count": len(lesson_plans),
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
            lesson_plans=lesson_plans,
            knowledge_points=knowledge_points,
            strategy=strategy,
        )
        generation_result = llm_service.generate_structured_output(
            messages=llm_messages,
            response_model=AssessmentGenerationResult,
        )
        _truncate_questions_to_strategy(generation_result, expected_question_count=int(strategy["question_count"]))
        _validate_assessment_result(
            generation_result,
            strategy=strategy,
            knowledge_point_ids={point.id for point in knowledge_points},
        )
        _normalize_assessment_distributions(generation_result)

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
        _mark_step(step_map["finalize_assessment_task"], TASK_STATUS_PROCESSING, 70, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="finalize_assessment_task", progress_percent=90)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        finished_at = DateTimeUtil.now_utc()
        _mark_step(
            step_map["finalize_assessment_task"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"assessment_blueprint_id": assessment_blueprint.id, "paper_result_id": paper_result.id},
            finished_at=finished_at,
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="finalize_assessment_task",
            progress_percent=100,
            result_json={
                "generation_batch_id": generation_batch.id,
                "assessment_blueprint_id": assessment_blueprint.id,
                "paper_result_id": paper_result.id,
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
            "assessment_blueprint_id": assessment_blueprint.id,
            "paper_result_id": paper_result.id,
            "question_count": len(generation_result.questions),
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
    lesson_plans: list,
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
        "lesson_plans": [
            {
                "id": lesson_plan.id,
                "class_session_no": lesson_plan.class_session_no,
                "lesson_title": lesson_plan.lesson_title,
                "summary_text": lesson_plan.summary_text,
                "content_json": lesson_plan.content_json,
            }
            for lesson_plan in lesson_plans
        ],
        "knowledge_points": point_payload,
        "assessment_strategy": strategy,
    }
    scene_type = str(strategy["scene_type"])
    scenario_type = str(strategy["scenario_type"])
    system_prompt = (
        "你是测评蓝图和题目生成助手。"
        f"当前策略场景为 scene_type={scene_type}、scenario_type={scenario_type}，"
        "请基于课程大纲、批次内教案和知识点生成与该场景一致的中文测评蓝图与题目，"
        "不得固定写成单元测试；blueprint_name、paper_title、strategy_summary 和题目语境必须体现当前场景。"
        "必须严格输出 JSON 对象，字段包含 blueprint_name、paper_title、strategy_summary、"
        "knowledge_weights、question_type_distribution、difficulty_distribution、questions。"
        "questions 数量必须不少于 assessment_strategy.question_count，只能多不能少；"
        "如不确定可适当多出几道，多余题目会按题号顺序被截断，但绝不允许少于该题量。"
        "question_no 必须从 1 开始连续递增且不得重复。"
        "question_type_distribution 和 difficulty_distribution 必须与 questions 逐题统计完全一致。"
        "每道题必须包含 knowledge_point_id、question_type、difficulty_level、stem_text、answer_text、analysis_text。"
        "所有 knowledge_point_id 必须只引用输入中的知识点 id，题型只能使用输入策略中的 question_types。"
        "不要输出 Markdown、解释文字或代码块。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _truncate_questions_to_strategy(
    result: AssessmentGenerationResult,
    *,
    expected_question_count: int,
) -> None:
    """LLM 允许多出题目，按题号顺序截断到策略题量；不足时不处理交由校验失败。"""
    if len(result.questions) <= expected_question_count:
        return
    ordered_questions = sorted(result.questions, key=lambda question: question.question_no)
    result.questions = ordered_questions[:expected_question_count]


def _validate_assessment_result(
    result: AssessmentGenerationResult,
    *,
    strategy: dict[str, Any],
    knowledge_point_ids: set[int],
) -> None:
    """校验测评生成结果。"""
    expected_question_count = int(strategy["question_count"])
    if len(result.questions) < expected_question_count:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回题量不足测评策略要求",
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


def _normalize_assessment_distributions(result: AssessmentGenerationResult) -> None:
    """以后端题目明细统计为准修正汇总分布与知识点权重。"""
    result.question_type_distribution = _build_question_type_distribution(result)
    result.difficulty_distribution = _build_question_difficulty_distribution(result)
    result.knowledge_weights = _build_knowledge_weights(result)


def _build_knowledge_weights(result: AssessmentGenerationResult) -> list[AssessmentKnowledgeWeightDraft]:
    """根据题目明细反算知识点建议题量与考查权重，并保留 LLM 的题型/难度建议。"""
    total_question_count = len(result.questions) or 1
    ordered_point_ids: list[int] = []
    actual_counts: dict[int, int] = {}
    question_types_by_point: dict[int, list[str]] = {}
    difficulties_by_point: dict[int, list[int]] = {}
    for question in result.questions:
        point_id = question.knowledge_point_id
        if point_id not in actual_counts:
            ordered_point_ids.append(point_id)
            question_types_by_point[point_id] = []
            difficulties_by_point[point_id] = []
        actual_counts[point_id] = actual_counts.get(point_id, 0) + 1
        if question.question_type not in question_types_by_point[point_id]:
            question_types_by_point[point_id].append(question.question_type)
        difficulties_by_point[point_id].append(question.difficulty_level)

    llm_hints = {item.knowledge_point_id: item for item in result.knowledge_weights}
    normalized: list[AssessmentKnowledgeWeightDraft] = []
    for point_id in ordered_point_ids:
        count = actual_counts[point_id]
        hint = llm_hints.get(point_id)
        difficulties = sorted(difficulties_by_point[point_id])
        normalized.append(
            AssessmentKnowledgeWeightDraft(
                knowledge_point_id=point_id,
                weight_percent=round(count / total_question_count * 100, 2),
                suggested_question_count=count,
                question_types=(
                    hint.question_types if hint and hint.question_types else question_types_by_point[point_id]
                ),
                difficulty_range=(
                    hint.difficulty_range if hint and hint.difficulty_range else [difficulties[0], difficulties[-1]]
                ),
            )
        )
    return normalized


def _build_blueprint_content_json(result: AssessmentGenerationResult) -> dict[str, Any]:
    """构造测评蓝图内容 JSON。"""
    return {
        "strategy_summary": result.strategy_summary,
        "knowledge_weights": [item.model_dump(mode="json") for item in result.knowledge_weights],
        "question_type_distribution": result.question_type_distribution,
        "difficulty_distribution": result.difficulty_distribution,
    }


def _build_question_type_distribution(result: AssessmentGenerationResult) -> dict[str, int]:
    """根据题目明细统计题型分布。"""
    stats: dict[str, int] = {}
    for question in result.questions:
        key = str(question.question_type)
        stats[key] = stats.get(key, 0) + 1
    return stats


def _build_question_difficulty_distribution(result: AssessmentGenerationResult) -> dict[str, int]:
    """根据题目明细统计难度分布。"""
    stats: dict[str, int] = {}
    for question in result.questions:
        key = str(question.difficulty_level)
        stats[key] = stats.get(key, 0) + 1
    return stats


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
    return _build_question_difficulty_distribution(result)


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
            "finalize_assessment_task",
        )
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: AssessmentRepository, payload: dict, exc: Exception) -> None:
    """处理测评生成任务失败：可重试错误重排重试，否则判终态失败。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.ASSESSMENT_TASK_FAILED,
    )


def _create_session(payload: dict) -> Session:
    """为测评生成任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
