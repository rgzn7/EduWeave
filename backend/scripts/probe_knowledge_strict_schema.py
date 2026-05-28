"""
@Date: 2026-05-28
@Author: xisy
@Discription: 真实调用上游 LLM，验证 KnowledgeChapterPointExtractionResult 在 strict_schema=True 下不会被 400 拒绝
"""

import json
import sys
import traceback
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.knowledge.schemas import KnowledgeChapterPointExtractionResult
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService
from app.shared.llm.service import _to_openai_strict_schema


def _dump_strict_schema_shape() -> None:
    """打印 strict 形态摘要，便于人工核对。"""
    schema = KnowledgeChapterPointExtractionResult.model_json_schema()
    strict = _to_openai_strict_schema(schema)
    point_schema = (strict.get("$defs") or {}).get("KnowledgePointLlmDraft") or {}
    evidence_schema = (strict.get("$defs") or {}).get("KnowledgeEvidenceLlmDraft") or {}
    print("[strict schema] top required:", strict.get("required"))
    print("[strict schema] additionalProperties:", strict.get("additionalProperties"))
    print("[strict schema] $defs:", list((strict.get("$defs") or {}).keys()))
    print("[strict schema] KnowledgePointLlmDraft required:", point_schema.get("required"))
    print("[strict schema] KnowledgeEvidenceLlmDraft properties:", list((evidence_schema.get("properties") or {}).keys()))


def _build_minimal_messages() -> list[ChatMessage]:
    """构造最小章节输入，让模型只需抽取 1 个知识点即可命中校验。"""
    payload = {
        "parse_version_id": 1,
        "chapter": {
            "node_path": "1",
            "title": "第一章 整数乘法",
            "page_start": 1,
            "page_end": 1,
            "line_start": 1,
            "line_end": 3,
        },
        "markdown": "# 第一章 整数乘法\n两位数乘一位数可以用竖式计算。\n计算时要注意进位。",
    }
    role_prompt = (
        "你是教材知识点抽取助手。请只输出中文 JSON 对象，不能输出 Markdown、解释文字或代码块。"
        "summary_json 必须且只能包含 overview 字符串和 key_terms 字符串数组；"
        "knowledge_points 只输出 1 个知识点；"
        "tags_json 必须且只能包含 tags 字符串数组；"
        "evidences 每项字段只包含 page_no、block_no、evidence_type、excerpt_text、score_value，page_no 必须为 1。"
    )
    user_text = "请严格以 JSON 对象格式输出知识点抽取结果。" + json.dumps(payload, ensure_ascii=False)
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
            response_model=KnowledgeChapterPointExtractionResult,
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
    print("summary_json:", result.summary_json.model_dump() if result.summary_json is not None else None)
    print("knowledge_points count:", len(result.knowledge_points))
    print("point_names:", [point.point_name for point in result.knowledge_points])
    return 0


if __name__ == "__main__":
    sys.exit(main())
