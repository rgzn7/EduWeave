"""
@Date: 2026-05-27
@Author: xisy
@Discription: 真实调用上游 LLM，验证 CurriculumGenerationResult 在 strict_schema=True 下不会被 400 拒绝
"""

import json
import sys
import traceback
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.curriculum.tasks import _validate_curriculum_result
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.llm.service import _to_openai_strict_schema


def _dump_strict_schema_shape() -> None:
    """打印 strict 形态摘要，便于人工核对。"""
    schema = CurriculumGenerationResult.model_json_schema()
    strict = _to_openai_strict_schema(schema)
    overview_schema = (strict.get("$defs") or {}).get("CurriculumCourseOverview") or {}
    print("[strict schema] top required:", strict.get("required"))
    print("[strict schema] additionalProperties:", strict.get("additionalProperties"))
    print("[strict schema] $defs:", list((strict.get("$defs") or {}).keys()))
    print("[strict schema] CurriculumCourseOverview required:", overview_schema.get("required"))


def _build_minimal_messages() -> list[ChatMessage]:
    """构造最小知识点 + 单课次输入，让模型只需输出 1 个课次大纲即可命中校验。"""
    payload = {
        "project": {
            "id": 1,
            "name": "三年级数学提升",
            "subject_code": "math",
            "grade_code": "grade_3",
            "applicable_target": "三年级学生",
            "remark": None,
        },
        "generation_batch": {
            "id": 1,
            "batch_no": "BATCH-STRICT-PROBE",
            "course_count": 1,
            "session_duration_minutes": 40,
            "chapter_range_json": None,
        },
        "knowledge_points": [
            {
                "id": 1001,
                "chapter_node_id": 1,
                "point_name": "整数乘法",
                "importance_level": 4,
                "difficulty_level": 2,
                "mastery_level_hint": "记忆",
                "summary_text": "掌握两位数乘一位数的算法。",
            }
        ],
        "learner_profile": {
            "summary_text": "学生已具备基本加法基础，乘法竖式需要强化。",
            "grade_code": "grade_3",
            "subject_scope": "math",
        },
    }
    role_prompt = (
        "你是课程大纲生成助手。请只输出中文课程大纲 JSON 对象，不能输出 Markdown、解释文字或代码块。"
        "course_overview 必须且只能包含 audience、objective、duration 三个字符串字段；"
        "lesson_sessions 必须只包含 1 个课次，session_no=1，knowledge_point_refs 必须为 [1001]；"
        "coverage_knowledge_points 必须等于所有 lesson_sessions.knowledge_point_refs 的并集，且必须为 [1001]。"
    )
    user_text = "请严格以 JSON 对象格式输出课程大纲。" + json.dumps(payload, ensure_ascii=False)
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
            response_model=CurriculumGenerationResult,
            strict_schema=True,
        )
        _validate_curriculum_result(result, course_count=1, knowledge_point_ids={1001})
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] strict_schema=True 调用或业务校验抛出异常：")
        traceback.print_exc()
        details = getattr(exc, "details", None)
        if details is not None:
            print("\n[upstream error details]")
            print(json.dumps(details, ensure_ascii=False, indent=2)[:4000])
        return 1
    print("[OK] strict_schema=True 调用成功")
    print("plan_title:", result.plan_title)
    print("course_overview:", result.course_overview.model_dump())
    print("lesson_sessions count:", len(result.lesson_sessions))
    print("coverage_knowledge_points:", result.coverage_knowledge_points)
    return 0


if __name__ == "__main__":
    sys.exit(main())
