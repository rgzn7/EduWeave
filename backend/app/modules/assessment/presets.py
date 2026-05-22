"""
@Date: 2026-05-22
@Author: xisy
@Discription: 测练场景预设定义与策略解析
"""

from enum import Enum
from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode


class SceneType(str, Enum):
    """测练场景类型。"""

    HOMEWORK = "homework"
    UNIT_TEST = "unit_test"
    FINAL_EXAM = "final_exam"


# 三类测练场景预设：题量、允许题型、难度区间与场景化 prompt 约束统一锁定在此，
# 调用方仅需指定 scene_type，后端自动套用对应预设，不再接受任意策略 JSON。
ASSESSMENT_SCENE_PRESETS: dict[str, dict[str, Any]] = {
    SceneType.HOMEWORK.value: {
        "scene_label": "课后作业",
        "question_count": 6,
        "question_types": ["single_choice", "fill_blank", "short_answer"],
        "difficulty_range": [1, 3],
        "prompt_constraint": (
            "本次为课后作业，题目须紧扣课后练习场景，聚焦当堂知识点的巩固与基础应用，"
            "难度偏基础、题量精简，避免偏题怪题。"
        ),
    },
    SceneType.UNIT_TEST.value: {
        "scene_label": "单元测试",
        "question_count": 10,
        "question_types": ["single_choice", "fill_blank", "short_answer"],
        "difficulty_range": [2, 4],
        "prompt_constraint": (
            "本次为单元测试，题目须覆盖本单元主要知识点，难度中等，"
            "兼顾概念理解与典型应用，具备基本区分度。"
        ),
    },
    SceneType.FINAL_EXAM.value: {
        "scene_label": "期末综合测",
        "question_count": 20,
        "question_types": ["single_choice", "fill_blank", "short_answer"],
        "difficulty_range": [2, 5],
        "prompt_constraint": (
            "本次为期末综合测评，题目须覆盖更广的知识点范围，注重知识点之间的综合运用与区分度，"
            "并包含一定比例的较高难度题。"
        ),
    },
}

DEFAULT_ASSESSMENT_SCENE_TYPE = SceneType.UNIT_TEST.value


def resolve_assessment_strategy(scene_type: str | None) -> dict[str, Any]:
    """根据测练场景套用预设策略。

    scene_type 为空时回退默认单元测试场景；非法场景抛出业务异常。
    """
    effective_scene_type = str(scene_type or DEFAULT_ASSESSMENT_SCENE_TYPE)
    preset = ASSESSMENT_SCENE_PRESETS.get(effective_scene_type)
    if preset is None:
        raise AppException(
            BusinessErrorCode.ASSESSMENT_SCENE_INVALID,
            "不支持的测练场景类型",
            {
                "scene_type": effective_scene_type,
                "supported_scene_types": sorted(ASSESSMENT_SCENE_PRESETS),
            },
        )
    return {
        "scenario_type": effective_scene_type,
        "scene_type": effective_scene_type,
        "scene_label": preset["scene_label"],
        "question_count": preset["question_count"],
        "question_types": list(preset["question_types"]),
        "difficulty_range": list(preset["difficulty_range"]),
        "prompt_constraint": preset["prompt_constraint"],
    }
