# @Date: 2026-05-25
# @Author: xisy
# @Discription: 教案 prompt cache 实测脚本：以教案的稳定前缀结构连续发两次请求，
#               读取 usage 中的缓存命中字段，验证上游前缀缓存是否生效（兼容 chat / responses）

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402


# 模拟教案 system 前半段（角色与字段定义），与 lesson_plan/tasks.py 中拆分后的常量保持等长度
_ROLE_AND_SCHEMA_PROMPT = (
    "你是教案生成助手。请基于课程大纲中的 target_lesson_session、教材知识点和学生学情生成中文教师教案。"
    "必须严格输出 JSON 对象，字段如下，类型必须严格匹配，不允许将字符串字段替换为对象或数组："
    "lesson_title（字符串，不超过 255 字）；summary_text（字符串）；"
    "course_overview（对象，可包含 audience、duration、focus 等键，禁止使用字符串或数组）；"
    "material_list（字符串数组）；core_knowledge（字符串数组）；"
    "teaching_flow（对象数组，每项必须包含 step_no、stage_name、duration_minutes、teacher_actions、"
    "student_activities、knowledge_point_refs）；"
    "session_plans（对象数组，必须且只能包含 1 个课次安排，每项包含 session_no、title、objectives、"
    "teaching_focus、teaching_steps、homework、knowledge_point_refs）；"
    "after_class_plan（对象）；learner_adjustments（字符串数组）；knowledge_point_refs（整数数组）。"
)

_OUTPUT_RULES_PROMPT = (
    "teaching_flow 和 session_plans 中的 knowledge_point_refs 必须只引用输入中的知识点 id。"
    "教案需覆盖课程概述、物料清单、核心知识、导入、讲解、练习、总结和课后安排。"
    "不得返回空数组或空对象骨架；教师动作、学生活动、课次目标、教学重点、课后任务和学情适配都必须有可执行内容。"
    "不要输出 Markdown、解释文字或代码块。"
)


def _build_stable_user_payload(scale: int) -> str:
    """构造模拟教案稳定 user 上下文，含项目/大纲/知识点/学情等大段稳定数据。"""
    knowledge_points = [
        {
            "id": idx,
            "chapter_node_id": (idx - 1) // 5 + 1,
            "point_name": f"测试知识点{idx}",
            "importance_level": (idx % 5) + 1,
            "difficulty_level": (idx % 4) + 1,
            "summary_text": "占位摘要，用于撑长稳定前缀以触达上游自动缓存阈值。" * 2,
        }
        for idx in range(1, 30 * scale + 1)
    ]
    profile_records = [
        {
            "student_key": f"stu_{idx}",
            "student_name": f"学生{idx}",
            "grade_code": "G3",
            "subject_code": "math",
            "score_value": 60 + (idx % 40),
            "advantage_tags_json": {"tags": ["计算", "阅读"]},
            "weakness_tags_json": {"tags": ["几何", "理解"]},
            "summary_text": "占位画像摘要，用于撑长稳定前缀以触达上游自动缓存阈值。",
        }
        for idx in range(1, 10 * scale + 1)
    ]
    payload = {
        "project": {
            "id": 1,
            "name": "三年级数学乘法提升测试项目",
            "subject_code": "math",
            "grade_code": "G3",
            "applicable_target": "三年级学生群体",
            "remark": "用于 prompt cache 实测，不写入生产数据库",
        },
        "generation_batch": {
            "id": 999,
            "batch_no": "test-batch-001",
            "course_count": 12,
            "session_duration_minutes": 90,
            "chapter_range_json": {"chapter_ids": [1, 2, 3]},
        },
        "curriculum_plan": {
            "id": 1,
            "plan_title": "三年级数学乘法提升课程",
            "summary_text": "围绕乘法口诀与初步应用展开 12 课次的连贯训练。",
            "content_json": {"course_overview": {"audience": "三年级", "duration": "12 课次"}},
        },
        "knowledge_points": knowledge_points,
        "learner_profile_version": {
            "id": 1,
            "summary_text": "10 名三年级学生学情画像汇总。",
            "grade_code": "G3",
            "subject_scope": ["math"],
            "records": profile_records,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_variable_user_text(session_no: int) -> str:
    """构造每次循环变化的本课次目标段。"""
    return (
        "请基于上述稳定上下文与下方 target_lesson_session 严格以 JSON 对象输出本课次教案：\n"
        + json.dumps(
            {
                "target_lesson_session": {
                    "session_no": session_no,
                    "title": f"第{session_no}讲 测试课次",
                    "objectives": ["掌握当前课次的核心知识点", "完成课堂练习"],
                    "key_points": ["重点 A", "重点 B"],
                }
            },
            ensure_ascii=False,
        )
    )


def _resolve_cached_tokens(usage: dict) -> int:
    """从不同协议的 usage 结构里提取缓存命中 token 数（与 service.build_usage 保持一致）。"""
    if not isinstance(usage, dict):
        return 0
    for key in ("input_tokens_details", "prompt_tokens_details"):
        details = usage.get(key)
        if isinstance(details, dict):
            value = details.get("cached_tokens")
            if isinstance(value, int):
                return value
    fallback = usage.get("cache_read_input_tokens")
    return int(fallback) if isinstance(fallback, int) else 0


def _resolve_prompt_tokens(usage: dict) -> int:
    """统一读取 prompt/input tokens（兼容 Chat 与 Responses）。"""
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)


def _build_messages(stable_user_text: str, variable_user_text: str, *, explicit_cache: bool, api_format: str) -> list[dict]:
    """构造与 EduWeave 教案 4 消息布局一致的请求消息（按需挂 Anthropic 风格 cache_control）。"""
    block_type = "text" if api_format == "chat" else "input_text"
    stable_user_block = {"type": block_type, "text": stable_user_text}
    if explicit_cache:
        stable_user_block["cache_control"] = {"type": "ephemeral"}
    return [
        {"role": "system", "content": _ROLE_AND_SCHEMA_PROMPT},
        {"role": "system", "content": _OUTPUT_RULES_PROMPT},
        {"role": "user", "content": [stable_user_block]},
        {"role": "user", "content": variable_user_text},
    ]


async def _call_once(
    *,
    base_url: str,
    api_key: str,
    model: str,
    api_format: str,
    messages: list[dict],
    reasoning_effort: str | None,
    prompt_cache_key: str | None,
    user_id: str | None,
) -> dict:
    """按指定协议格式发一次 LLM 请求，返回完整 JSON。"""
    if api_format == "chat":
        path = "/chat/completions"
        payload: dict = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
    else:
        path = "/responses"
        payload = {
            "model": model,
            "input": messages,
            "stream": False,
        }
    if reasoning_effort:
        if api_format == "chat":
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["reasoning"] = {"effort": reasoning_effort}
    if prompt_cache_key:
        payload["prompt_cache_key"] = prompt_cache_key
    if user_id:
        payload["user"] = user_id

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base_url}{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"上游请求失败 status={response.status_code} body={response.text[:600]}"
            )
        return response.json()


async def main() -> None:
    parser = argparse.ArgumentParser(description="EduWeave 教案 prompt cache 实测")
    parser.add_argument("--model", default=None, help="覆盖默认 llm_model")
    parser.add_argument("--scale", type=int, default=1, help="稳定前缀膨胀倍数（默认 1，约 5K+ 字符）")
    parser.add_argument(
        "--api-format",
        choices=["chat", "response"],
        default=None,
        help="覆盖 settings.llm_api_format（默认走配置）",
    )
    parser.add_argument(
        "--reasoning",
        default="none",
        help='推理强度: "none" 表示不传 reasoning 字段，其余原样下发',
    )
    parser.add_argument(
        "--explicit-cache",
        action="store_true",
        help="给稳定 user 消息挂 Anthropic 风格的 cache_control:ephemeral（仅 Anthropic 兼容端有效）",
    )
    parser.add_argument(
        "--prompt-cache-key",
        default="eduweave-lesson-batch-999",
        help="prompt_cache_key（同 key 命中同一缓存分片），传 'none' 表示不带",
    )
    parser.add_argument(
        "--user",
        default="none",
        help="user 字段（辅助代理按 user 做缓存分片），传 'none' 表示不带",
    )
    args = parser.parse_args()

    settings = get_settings()
    base_url = settings.llm_api_base_url.rstrip("/")
    api_key = settings.llm_api_key
    model = args.model or settings.llm_model
    api_format = args.api_format or settings.llm_api_format
    if api_format == "responses":
        api_format = "response"
    if not (base_url and api_key and model):
        raise SystemExit("LLM_API_BASE_URL / LLM_API_KEY / LLM_MODEL 未配置完整，无法运行")

    reasoning_effort = None if args.reasoning.lower() == "none" else args.reasoning
    prompt_cache_key = None if args.prompt_cache_key.lower() == "none" else args.prompt_cache_key
    user_id = None if args.user.lower() == "none" else args.user

    stable_user_text = _build_stable_user_payload(scale=max(1, args.scale))

    print("=" * 64)
    print(f"base_url           : {base_url}")
    print(f"model              : {model}")
    print(f"api_format         : {api_format}")
    print(f"reasoning_effort   : {reasoning_effort or '<omitted>'}")
    print(f"explicit_cache     : {args.explicit_cache}")
    print(f"prompt_cache_key   : {prompt_cache_key or '<omitted>'}")
    print(f"user               : {user_id or '<omitted>'}")
    print(f"stable_user chars  : {len(stable_user_text)}")
    print("=" * 64)

    results: list[dict] = []
    for round_index in (1, 2):
        print(f"\n--- 第 {round_index} 次请求（session_no={round_index}）---")
        messages = _build_messages(
            stable_user_text,
            _build_variable_user_text(session_no=round_index),
            explicit_cache=args.explicit_cache,
            api_format=api_format,
        )
        started_at = time.perf_counter()
        data = await _call_once(
            base_url=base_url,
            api_key=api_key,
            model=model,
            api_format=api_format,
            messages=messages,
            reasoning_effort=reasoning_effort,
            prompt_cache_key=prompt_cache_key,
            user_id=user_id,
        )
        elapsed = time.perf_counter() - started_at
        usage = data.get("usage") or {}
        cached_tokens = _resolve_cached_tokens(usage)
        prompt_tokens = _resolve_prompt_tokens(usage)
        print(f"elapsed            : {elapsed:.2f}s")
        print(f"prompt_tokens      : {prompt_tokens}")
        print(f"cached_tokens      : {cached_tokens}")
        print(f"usage raw          : {json.dumps(usage, ensure_ascii=False)}")
        results.append({"prompt_tokens": prompt_tokens, "cached_tokens": cached_tokens, "elapsed": elapsed})

    print("\n" + "=" * 64)
    first, second = results
    print(f"首次 prompt_tokens : {first['prompt_tokens']}  cached_tokens: {first['cached_tokens']}")
    print(f"二次 prompt_tokens : {second['prompt_tokens']}  cached_tokens: {second['cached_tokens']}")
    if second["cached_tokens"] > 0:
        ratio = second["cached_tokens"] / max(1, second["prompt_tokens"])
        print(f"前缀缓存命中比例   : {ratio:.1%}（上游已启用前缀缓存）")
    else:
        print("二次未命中前缀缓存：检查 prompt_cache_key、稳定前缀长度（需 >= 1024 tokens）、上游是否支持。")


if __name__ == "__main__":
    asyncio.run(main())
