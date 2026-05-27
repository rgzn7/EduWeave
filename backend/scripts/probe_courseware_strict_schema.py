"""
@Date: 2026-05-27
@Author: xisy
@Discription: 真实调用上游 LLM，验证 SlideDeckGenerationResult 在 strict_schema=True 下不会被 400 拒绝
"""

import json
import sys
import traceback

from app.modules.courseware.schemas import SlideDeckGenerationResult
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.llm.service import _to_openai_strict_schema


def _dump_strict_schema_shape() -> None:
    """打印 strict 形态摘要，便于人工核对。"""
    schema = SlideDeckGenerationResult.model_json_schema()
    strict = _to_openai_strict_schema(schema)
    slide_draft_schema = (strict.get("$defs") or {}).get("SlideDraft") or {}
    slide_type_schema = (slide_draft_schema.get("properties") or {}).get("slide_type") or {}
    print("[strict schema] top required:", strict.get("required"))
    print("[strict schema] additionalProperties:", strict.get("additionalProperties"))
    print("[strict schema] $defs:", list((strict.get("$defs") or {}).keys()))
    print("[strict schema] SlideDraft.slide_type enum:", slide_type_schema.get("enum"))


def _build_minimal_messages() -> list[ChatMessage]:
    """构造最小课件输入，让模型只需输出 1 页封面即可命中校验。"""
    payload = {
        "project": {
            "id": 1,
            "name": "三年级数学提升",
            "subject_code": "math",
            "grade_code": "grade_3",
            "applicable_target": "三年级学生",
        },
        "lesson_plan": {
            "lesson_title": "整数乘法入门",
            "summary_text": "帮助学生掌握两位数乘一位数的基本算法。",
        },
        "knowledge_points": [
            {
                "id": 1001,
                "point_name": "整数乘法",
                "importance_level": 4,
                "difficulty_level": 2,
                "summary_text": "掌握两位数乘一位数的算法。",
            }
        ],
    }
    role_prompt = (
        "你是课件结构设计助手。请只输出一份中文课件 JSON 对象，不能输出 Markdown、解释文字或代码块。"
        "本次只生成 1 页封面页：deck_title 为字符串；slides 为长度 1 的数组；"
        "唯一页面必须包含 slide_no=1、slide_type=\"cover\"、title、bullet_points、speaker_notes、"
        "knowledge_point_refs、example_block。封面页 bullet_points 和 knowledge_point_refs 使用空数组，"
        "speaker_notes 和 example_block 使用 null。"
    )
    user_text = "请严格以 JSON 对象格式输出课件结构。" + json.dumps(payload, ensure_ascii=False)
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
            response_model=SlideDeckGenerationResult,
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
    print("deck_title:", result.deck_title)
    print("slides count:", len(result.slides))
    print("slide_types:", [slide.slide_type for slide in result.slides])
    return 0


if __name__ == "__main__":
    sys.exit(main())
