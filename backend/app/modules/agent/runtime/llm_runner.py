"""
@Date: 2026-05-31
@Author: xisy
@Discription: Agent 工具调用 LLM 客户端：以 Responses 协议驱动工具循环
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import Settings, get_settings
from app.shared.llm.client import OpenAICompatibleLlmClient
from app.shared.llm.prompt_cache import apply_prompt_cache_identity

logger = structlog.get_logger(__name__)


@dataclass
class AgentLLMResult:
    """单轮 LLM 调用的归一结果。"""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class AgentLLMRunner:
    """面向 Agent 工具循环的 Responses 协议客户端。"""

    def __init__(self, settings: Settings | None = None, client: OpenAICompatibleLlmClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleLlmClient(self.settings)

    def run_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        cache_biz_key: str | None = None,
        cache_user_id: int | None = None,
    ) -> AgentLLMResult:
        """执行一轮带工具的对话调用并返回装配后的结果。"""
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "input": messages,
            "tools": self._to_responses_tools(tools),
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning"] = {"effort": self.settings.llm_reasoning_effort}
        else:
            payload["temperature"] = self.settings.agent_temperature
        apply_prompt_cache_identity(
            payload,
            settings=self.settings,
            biz_key=cache_biz_key,
            user_id=cache_user_id,
        )

        streamed_text, final_response = self.client.create_response_stream(payload)
        final_response = final_response if isinstance(final_response, dict) else {}
        tool_calls = self._extract_function_calls(final_response)
        return AgentLLMResult(
            content=(streamed_text or "").strip(),
            tool_calls=tool_calls,
            finish_reason=self._extract_status(final_response),
            usage=final_response.get("usage") if isinstance(final_response.get("usage"), dict) else None,
        )

    @staticmethod
    def _to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把 Chat 形态工具定义转换为 Responses 扁平形态。"""
        responses_tools: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict):
                responses_tools.append({"type": "function", **function})
            elif isinstance(tool, dict) and tool.get("type") == "function" and tool.get("name"):
                responses_tools.append(tool)
        return responses_tools

    @staticmethod
    def _extract_function_calls(final_response: dict[str, Any]) -> list[dict[str, Any]]:
        """从 Responses 输出项中提取 function_call，归一为 {call_id, name, arguments}。"""
        output = final_response.get("output")
        if not isinstance(output, list):
            return []
        tool_calls: list[dict[str, Any]] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            arguments = item.get("arguments")
            tool_calls.append(
                {
                    "call_id": str(item.get("call_id") or item.get("id") or ""),
                    "name": name,
                    "arguments": arguments if isinstance(arguments, str) else "{}",
                }
            )
        return tool_calls

    @staticmethod
    def _extract_status(final_response: dict[str, Any]) -> str | None:
        """读取 Responses 顶层状态，用于诊断。"""
        status = final_response.get("status")
        return status if isinstance(status, str) else None

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
            logger.warning("agent_tool_arguments_parse_failed", raw_arguments=raw_arguments[:500])
            return {}
        return parsed if isinstance(parsed, dict) else {}
