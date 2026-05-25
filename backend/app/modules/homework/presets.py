"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业策略解析，复用测评 HOMEWORK 预设
"""

from typing import Any

from app.modules.assessment.presets import SceneType, resolve_assessment_strategy


def resolve_homework_strategy() -> dict[str, Any]:
    """获取课后作业生成策略。"""
    return resolve_assessment_strategy(SceneType.HOMEWORK.value)
