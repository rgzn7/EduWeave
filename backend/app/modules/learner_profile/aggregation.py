"""
@Date: 2026-05-29
@Author: xisy
@Discription: 班级学情画像 LLM 聚合能力（结构化结果模型与提示词构造）
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from app.shared.llm import ChatMessage


class ClassSubjectOverview(BaseModel):
    """班级单学科概览。"""

    subject_code: str = Field(description="学科编码，如 chinese/math/english/science")
    student_count: int = Field(description="该学科覆盖的学生数")
    score_avg: float = Field(description="该学科平均分；无有效分数时填 0")
    score_min: float = Field(description="该学科最低分；无有效分数时填 0")
    score_max: float = Field(description="该学科最高分；无有效分数时填 0")
    high_count: int = Field(description="高分层人数")
    mid_count: int = Field(description="中分层人数")
    low_count: int = Field(description="低分层人数")
    summary: str = Field(description="该学科班级整体表现简述")


class ClassTieredGroup(BaseModel):
    """班级分层学生分组。"""

    tier: str = Field(description="分层标识：high/mid/low")
    student_keys: list[str] = Field(description="该层包含的学生标识列表（取输入中的 student_key）")
    teaching_suggestions: list[str] = Field(description="针对该层的教学建议")


class ClassProfileGenerationResult(BaseModel):
    """班级学情画像聚合结果。"""

    class_summary: str = Field(description="班级整体学情摘要，用于驱动下游课程/课件/测练生成")
    grade_consistency: str = Field(description="班级年级一致性说明（如全部三年级，或存在不一致）")
    region_consistency: str = Field(description="班级地区一致性说明")
    warnings: list[str] = Field(description="数据异常提示（如年级/地区不一致、缺少分数等），无则空数组")
    subject_overview: list[ClassSubjectOverview] = Field(description="各学科班级概览")
    common_strengths: list[str] = Field(description="班级共性优势")
    common_weaknesses: list[str] = Field(description="班级共性薄弱点")
    common_habits: list[str] = Field(description="班级共性学习习惯")
    common_behaviors: list[str] = Field(description="班级共性行为特征")
    tiered_groups: list[ClassTieredGroup] = Field(description="高/中/低分层分组及教学建议")
    teaching_recommendations: list[str] = Field(description="面向全班、兼顾分层的整体教学建议")


def build_class_profile_messages(
    *,
    records: list,
    version_meta: dict[str, Any],
) -> list[ChatMessage]:
    """构造班级学情聚合提示词。

    records 为该班级所有学生×学科的画像记录（ORM 对象），version_meta 携带班级层面
    的元信息（班级名、年级范围、学科范围、学生数、年级分布等），供 LLM 做一致性判断。
    """
    record_payload = [
        {
            "student_key": record.student_key,
            "student_name": record.student_name,
            "is_anonymous": bool(record.is_anonymous),
            "region_name": record.region_name,
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
        for record in records
    ]
    user_payload = {
        "class_meta": version_meta,
        "records": record_payload,
    }
    system_prompt = (
        "你是班级学情聚合助手。输入是同一个班级若干学生的学情画像记录（每条对应一个学生的某个学科），"
        "请基于全班记录聚合出班级整体画像，用于驱动后续面向全班、可分层的课程大纲、教案、课件与测练生成。"
        "必须严格输出 JSON 对象，字段类型严格匹配，不允许嵌套替换："
        "class_summary（字符串，班级整体学情摘要）；"
        "grade_consistency、region_consistency（字符串，描述年级/地区是否一致）；"
        "warnings（字符串数组，数据异常提示；若学生年级或地区不一致、缺少分数等需在此说明，无异常则空数组）；"
        "subject_overview（对象数组，每项含 subject_code、student_count（整数）、score_avg/score_min/score_max（数字，"
        "无有效分数填 0）、high_count/mid_count/low_count（整数，按该学科分数高/中/低分层人数）、summary（字符串））；"
        "common_strengths、common_weaknesses、common_habits、common_behaviors（字符串数组，跨学生提炼的班级共性）；"
        "tiered_groups（对象数组，每项含 tier（取 high/mid/low）、student_keys（字符串数组，取输入 student_key）、"
        "teaching_suggestions（字符串数组））；"
        "teaching_recommendations（字符串数组，面向全班且兼顾分层的整体教学建议）。"
        "tiered_groups 的 student_keys 只能引用输入 records 中出现的 student_key。"
        "不要输出 Markdown、解释文字或代码块。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]
