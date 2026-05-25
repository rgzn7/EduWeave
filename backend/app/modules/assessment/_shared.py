"""
@Date: 2026-05-25
@Author: xisy
@Discription: 测评 / 课后作业生成共享工具：LLM 题目校验、分布归一化、知识点权重反算
"""

from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.assessment.schemas import (
    AssessmentGenerationResult,
    AssessmentKnowledgeWeightDraft,
)


def truncate_questions_to_strategy(
    result: AssessmentGenerationResult,
    *,
    expected_question_count: int,
) -> None:
    """LLM 允许多出题目，按题号顺序截断到策略题量；不足时不处理交由校验失败。"""
    if len(result.questions) <= expected_question_count:
        return
    ordered_questions = sorted(result.questions, key=lambda question: question.question_no)
    result.questions = ordered_questions[:expected_question_count]


def validate_assessment_result(
    result: AssessmentGenerationResult,
    *,
    strategy: dict[str, Any],
    knowledge_point_ids: set[int],
) -> None:
    """校验测评 / 作业生成结果。"""
    expected_question_count = int(strategy["question_count"])
    if len(result.questions) < expected_question_count:
        raise AppException(
            BusinessErrorCode.LLM_RESULT_INVALID,
            "LLM 返回题量不足策略要求",
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
            "LLM 返回了不存在的知识点引用",
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


def normalize_assessment_distributions(result: AssessmentGenerationResult) -> None:
    """以后端题目明细统计为准修正汇总分布与知识点权重。"""
    result.question_type_distribution = build_question_type_distribution(result)
    result.difficulty_distribution = build_question_difficulty_distribution(result)
    result.knowledge_weights = build_knowledge_weights(result)


def build_knowledge_weights(result: AssessmentGenerationResult) -> list[AssessmentKnowledgeWeightDraft]:
    """根据题目明细反算知识点建议题量与考查权重，并保留 LLM 的题型 / 难度建议。"""
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


def build_question_type_distribution(result: AssessmentGenerationResult) -> dict[str, int]:
    """根据题目明细统计题型分布。"""
    stats: dict[str, int] = {}
    for question in result.questions:
        key = str(question.question_type)
        stats[key] = stats.get(key, 0) + 1
    return stats


def build_question_difficulty_distribution(result: AssessmentGenerationResult) -> dict[str, int]:
    """根据题目明细统计难度分布。"""
    stats: dict[str, int] = {}
    for question in result.questions:
        key = str(question.difficulty_level)
        stats[key] = stats.get(key, 0) + 1
    return stats


def build_blueprint_content_json(result: AssessmentGenerationResult) -> dict[str, Any]:
    """构造蓝图内容 JSON（测评蓝图与作业蓝图共用）。"""
    return {
        "strategy_summary": result.strategy_summary,
        "knowledge_weights": [item.model_dump(mode="json") for item in result.knowledge_weights],
        "question_type_distribution": result.question_type_distribution,
        "difficulty_distribution": result.difficulty_distribution,
    }


def build_paper_content_json(
    result: AssessmentGenerationResult,
    *,
    strategy: dict[str, Any],
) -> dict[str, Any]:
    """构造试卷 / 作业内容 JSON。"""
    return {
        "paper_title": result.paper_title,
        "scene_type": strategy["scene_type"],
        "scene_label": strategy.get("scene_label") or strategy["scene_type"],
        "question_type_distribution": result.question_type_distribution,
        "difficulty_distribution": result.difficulty_distribution,
        "questions": [question.model_dump(mode="json") for question in result.questions],
    }


def build_difficulty_stats(result: AssessmentGenerationResult) -> dict[str, Any]:
    """构造难度统计快照。"""
    return build_question_difficulty_distribution(result)
