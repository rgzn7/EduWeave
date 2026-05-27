"""
@Date: 2026-05-27
@Author: xisy
@Discription: DOCX 渲染所用的中英文标签映射，统一把内部枚举/字段名转换为面向教师的中文展示
"""

from typing import Any

# 题型枚举到中文展示
QUESTION_TYPE_LABELS: dict[str, str] = {
    "single_choice": "单选题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
}

# 测练场景枚举到中文展示
SCENE_TYPE_LABELS: dict[str, str] = {
    "homework": "课后作业",
    "unit_test": "单元测试",
    "final_exam": "期末综合测",
}

# 难度等级到星级展示，1-5 对应渐进难度
DIFFICULTY_LEVEL_LABELS: dict[int, str] = {
    1: "★",
    2: "★★",
    3: "★★★",
    4: "★★★★",
    5: "★★★★★",
}

# 教案 course_overview 子字段到中文标签，按渲染顺序排列
LESSON_COURSE_OVERVIEW_LABELS: dict[str, str] = {
    "focus": "教学重点",
    "audience": "适用学情",
    "duration": "建议时长",
    "teaching_style": "授课方式",
}

# 教案 after_class_plan 子字段到中文标签，按渲染顺序排列
LESSON_AFTER_CLASS_LABELS: dict[str, str] = {
    "review": "复习巩固",
    "homework": "课后任务",
    "parent_communication": "家校沟通",
}


def labelize(value: Any, mapping: dict[Any, str], *, default: str | None = None) -> str:
    """按映射把内部值转为中文展示，缺省时回退到 default 或原值字符串。"""
    if value is None:
        return default if default is not None else ""
    label = mapping.get(value)
    if label is not None:
        return label
    return default if default is not None else str(value)


def iter_known_fields(raw: Any, label_map: dict[str, str]) -> list[tuple[str, Any]]:
    """按 label_map 顺序提取 raw 中存在的字段，返回 (中文标签, 原值) 列表。

    raw 不是 dict 时返回空列表；label_map 未声明的键不会输出，避免再次出现英文字段直露。
    """
    if not isinstance(raw, dict):
        return []
    pairs: list[tuple[str, Any]] = []
    for key, label in label_map.items():
        if key in raw and raw[key] not in (None, "", [], {}):
            pairs.append((label, raw[key]))
    return pairs
