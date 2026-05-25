"""
@Date: 2026-05-25
@Author: xisy
@Discription: LLM 提示词显式缓存协议字段注入工具，按业务键分片复用上游前缀缓存
"""

from typing import Any


def resolve_cache_key(settings: Any, biz_key: str) -> str:
    """按业务键拼接上游 prompt_cache_key（前缀来自 settings）。"""
    return f"{settings.llm_prompt_cache_key_prefix}-{biz_key}"


def apply_prompt_cache_identity(
    payload: dict[str, Any],
    *,
    settings: Any,
    biz_key: str | None,
    user_id: int | None = None,
) -> None:
    """注入 prompt_cache_key 与可选 user，提升多账号代理上的前缀缓存命中率。

    biz_key 为空或开关关闭时直接返回；user 字段默认关闭，部分 OpenAI 代理在 Responses
    模式下对 user 字段不兼容，需要时再显式开启。
    """
    if not biz_key:
        return
    if not getattr(settings, "llm_prompt_cache_identity_enabled", False):
        return
    payload["prompt_cache_key"] = resolve_cache_key(settings, biz_key)
    if getattr(settings, "llm_prompt_cache_user_enabled", False) and user_id is not None:
        payload["user"] = f"eduweave-user-{user_id}"


def apply_prompt_cache_markers(
    translated_messages: list[dict[str, Any]],
    *,
    settings: Any,
    api_format: str,
    stable_prefix_count: int,
) -> None:
    """给已经翻译为厂商格式的"稳定前缀"最后一条消息挂 cache_control 标记。

    仅 Anthropic 兼容端需要显式标记；OpenAI 兼容端靠稳定前缀自动缓存 + prompt_cache_key
    分片即可，本函数对 OpenAI 端是空操作（但不影响载荷，OpenAI 会忽略 cache_control）。

    - translated_messages 必须已是厂商目标格式（content 为 str 或 list[dict]）。
    - stable_prefix_count 表示前缀消息数量；为 0、超过列表长度或开关关闭则不操作。
    - 标记只挂在第 stable_prefix_count-1 条消息：
        - content 为 str：整段包装成单 block 数组并挂 cache_control
        - content 为 list：在最后一个 block 上挂 cache_control
    - api_format=="chat" 时 block type 为 text，否则为 input_text（Responses）。
    """
    if not getattr(settings, "llm_prompt_cache_explicit_markers", False):
        return
    if stable_prefix_count <= 0 or stable_prefix_count > len(translated_messages):
        return
    anchor = translated_messages[stable_prefix_count - 1]
    content = anchor.get("content")
    block_type = "text" if api_format == "chat" else "input_text"
    if isinstance(content, str):
        anchor["content"] = [
            {"type": block_type, "text": content, "cache_control": {"type": "ephemeral"}}
        ]
        return
    if isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = {"type": "ephemeral"}
