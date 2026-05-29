"""
@Date: 2026-05-29
@Author: xisy
@Discription: Agent 工具调用 LLM 客户端：流式读取 Chat Completions 并装配 content 与 tool_calls
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.llm.client import OpenAICompatibleLlmClient
from app.shared.llm.prompt_cache import apply_prompt_cache_identity


@dataclass
class AgentLLMResult:
    """单轮 LLM 调用的归一结果。"""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class AgentLLMRunner:
    """面向 Agent 工具循环的 Chat Completions 客户端。

    与结构化输出服务不同，本客户端会从流式增量中装配 tool_calls；同时兼容部分网关
    在末帧塞完整 message、或对 /chat/completions 直接返回非流式 JSON 的情况。
    """

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=float(self.settings.llm_timeout_seconds))

    def _build_headers(self) -> dict[str, str]:
        api_key = self.settings.llm_api_key
        if not api_key:
            raise AppException(BusinessErrorCode.SYSTEM_CONFIG_INVALID, "LLM_API_KEY 未配置")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def _build_url(self) -> str:
        return f"{self.settings.llm_api_base_url}/chat/completions"

    def run_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        cache_biz_key: str | None = None,
        cache_user_id: int | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> AgentLLMResult:
        """执行一轮带工具的对话调用并返回装配后的结果。"""
        if not self.settings.llm_model:
            raise AppException(BusinessErrorCode.SYSTEM_CONFIG_INVALID, "LLM_MODEL 未配置")
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        else:
            payload["temperature"] = self.settings.agent_temperature
        apply_prompt_cache_identity(
            payload,
            settings=self.settings,
            biz_key=cache_biz_key,
            user_id=cache_user_id,
        )
        max_retries = self.settings.llm_max_retries
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return self._stream_once(payload, on_text_delta=on_text_delta)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= max_retries:
                    break
        raise AppException(
            BusinessErrorCode.LLM_REQUEST_FAILED,
            "Agent LLM 调用失败",
            {"error": str(last_exc) if last_exc else "unknown"},
        )

    def _stream_once(
        self,
        payload: dict[str, Any],
        *,
        on_text_delta: Callable[[str], None] | None,
    ) -> AgentLLMResult:
        """读取一次 SSE 流并装配结果。"""
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None

        with self.http_client.stream("POST", self._build_url(), headers=self._build_headers(), json=payload) as response:
            if response.is_error:
                response.read()
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            # 部分网关对 /chat/completions 返回非流式 JSON，直接整体解析
            if "text/event-stream" not in content_type and "json" in content_type:
                response.read()
                return self._parse_non_stream(response.json())
            for event_type, data_text in OpenAICompatibleLlmClient._iter_sse_events(response):
                if data_text == "[DONE]":
                    break
                data = OpenAICompatibleLlmClient._parse_sse_json_data(data_text, event_type, api_format="chat")
                OpenAICompatibleLlmClient._raise_for_chat_stream_error(
                    data, max_chars=self.settings.llm_stream_error_detail_max_chars
                )
                if isinstance(data.get("usage"), dict):
                    usage = data["usage"]
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                if isinstance(choice.get("finish_reason"), str):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        content_parts.append(piece)
                        if on_text_delta is not None:
                            on_text_delta(piece)
                    self._accumulate_tool_calls(tool_calls_acc, delta.get("tool_calls"), streaming=True)
                # 个别网关在末帧塞完整 message（非 delta），仅在缺 delta 时兜底
                message = choice.get("message")
                if isinstance(message, dict):
                    if not content_parts and isinstance(message.get("content"), str):
                        content_parts.append(message["content"])
                    self._accumulate_tool_calls(tool_calls_acc, message.get("tool_calls"), streaming=False)

        return AgentLLMResult(
            content="".join(content_parts),
            tool_calls=self._finalize_tool_calls(tool_calls_acc),
            finish_reason=finish_reason,
            usage=usage,
        )

    def _parse_non_stream(self, payload: dict[str, Any]) -> AgentLLMResult:
        """解析非流式 Chat Completions 响应。"""
        if payload.get("error"):
            raise AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "Agent LLM 调用失败", {"payload": payload})
        choices = payload.get("choices") or []
        message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
        tool_calls_acc: dict[int, dict[str, str]] = {}
        self._accumulate_tool_calls(tool_calls_acc, message.get("tool_calls"), streaming=False)
        return AgentLLMResult(
            content=message.get("content") if isinstance(message.get("content"), str) else "",
            tool_calls=self._finalize_tool_calls(tool_calls_acc),
            finish_reason=choices[0].get("finish_reason") if choices else None,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
        )

    @staticmethod
    def _accumulate_tool_calls(
        acc: dict[int, dict[str, str]],
        tool_calls: Any,
        *,
        streaming: bool,
    ) -> None:
        """把流式/完整 tool_calls 片段按 index 累积。"""
        if not isinstance(tool_calls, list):
            return
        for position, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            index = tool_call.get("index")
            if not isinstance(index, int):
                index = position
            slot = acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool_call.get("id"):
                slot["id"] = str(tool_call["id"])
            function = tool_call.get("function")
            if isinstance(function, dict):
                if function.get("name"):
                    slot["name"] = str(function["name"])
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments:
                    # 流式片段需要拼接，完整 message 直接覆盖
                    slot["arguments"] = slot["arguments"] + arguments if streaming else arguments

    @staticmethod
    def _finalize_tool_calls(acc: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
        """按 index 顺序输出标准 tool_calls。"""
        tool_calls: list[dict[str, Any]] = []
        for index in sorted(acc.keys()):
            slot = acc[index]
            if not slot.get("name"):
                continue
            tool_calls.append(
                {
                    "id": slot.get("id") or f"call_{index}",
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot.get("arguments") or "{}"},
                }
            )
        return tool_calls

    @staticmethod
    def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
        """解析工具调用参数 JSON 字符串。"""
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str) or not raw_arguments.strip():
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
