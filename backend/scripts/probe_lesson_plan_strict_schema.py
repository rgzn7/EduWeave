"""
@Date: 2026-05-27
@Author: xisy
@Discription: 真实调用上游 LLM，验证 LessonPlanGenerationResult 在 strict_schema=True 下不会被 400 拒绝
"""

import json
import sys
import traceback

from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.llm.service import _to_openai_strict_schema


def _dump_strict_schema_shape() -> None:
    """打印 strict 形态摘要，便于人工核对。"""
    schema = LessonPlanGenerationResult.model_json_schema()
    strict = _to_openai_strict_schema(schema)
    print("[strict schema] top required:", strict.get("required"))
    print("[strict schema] additionalProperties:", strict.get("additionalProperties"))
    print("[strict schema] $defs:", list((strict.get("$defs") or {}).keys()))


def _build_minimal_messages() -> list[ChatMessage]:
    """最小知识点 + 单课次输入，让模型只需输出 1 个课次教案即可命中校验。"""
    knowledge_points = [
        {
            "id": 1001,
            "chapter_node_id": 1,
            "point_name": "整数乘法",
            "importance_level": 4,
            "difficulty_level": 2,
            "mastery_level_hint": "记忆",
            "tags_json": {"tags": ["基础"]},
            "summary_text": "掌握两位数乘一位数的算法。",
        }
    ]
    target_lesson_session = {
        "session_no": 1,
        "title": "第1讲 整数乘法",
        "duration_minutes": 40,
        "objectives": ["掌握两位数乘一位数"],
        "key_points": ["乘法竖式"],
        "activities": ["口算热身", "例题讲解"],
        "homework": ["完成口算题"],
        "knowledge_point_refs": [1001],
    }
    stable_payload = {
        "project": {
            "id": 1,
            "name": "三年级数学提升",
            "subject_code": "math",
            "grade_code": "grade_3",
            "applicable_target": "三年级学生",
            "remark": None,
        },
        "knowledge_points": knowledge_points,
    }
    role_prompt = (
        "你是教案生成助手。请基于 target_lesson_session 输出一份中文教师教案 JSON。"
        "course_overview 必须包含 audience/duration/focus 三个字符串字段；"
        "after_class_plan 必须包含 review/homework/parent_communication 三个字符串字段；"
        "knowledge_point_refs 只能引用输入中的 id（本次仅 [1001]）。"
    )
    user_text = "请严格以 JSON 对象格式输出教案。" + json.dumps(
        {"stable": stable_payload, "target_lesson_session": target_lesson_session},
        ensure_ascii=False,
    )
    return [
        ChatMessage(role="system", content=role_prompt),
        ChatMessage(role="user", content=user_text),
    ]


def main() -> int:
    """执行真实请求并打印结果。"""
    _dump_strict_schema_shape()
    llm_service = OpenAICompatibleLlmService()
    messages = _build_minimal_messages()
    try:
        result = llm_service.generate_structured_output(
            messages=messages,
            response_model=LessonPlanGenerationResult,
            strict_schema=True,
        )
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] strict_schema=True 调用抛出异常：")
        traceback.print_exc()
        details = getattr(exc, "details", None)
        if details is not None:
            print("\n[upstream error details]")
            print(json.dumps(details, ensure_ascii=False, indent=2)[:4000])
        return 1
    print("[OK] strict_schema=True 调用成功")
    print("lesson_title:", result.lesson_title)
    print("course_overview:", result.course_overview.model_dump())
    print("after_class_plan:", result.after_class_plan.model_dump())
    print("teaching_flow steps:", len(result.teaching_flow))
    print("session_plans count:", len(result.session_plans))
    print("knowledge_point_refs:", result.knowledge_point_refs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
