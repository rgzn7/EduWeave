"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具调用守护：配额、重复调用与写前读校验
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings


class AgentToolCallGuard:
    """工具调用守护器，独立处理运行内配额与可恢复拒绝。"""

    def __init__(self, settings: Settings, tool_registry: Any) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self.tool_call_count = 0
        self.tool_signature_counts: dict[str, int] = {}
        self.tool_quota_exhausted_reason: str | None = None
        self._quota_notice_emitted = False

    def trigger_final_round(self, reason: str) -> None:
        """标记本次运行进入「禁止工具、必须出最终回答」的终结态。"""
        if self.tool_quota_exhausted_reason is None:
            self.tool_quota_exhausted_reason = reason

    def record_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """记录工具调用并执行配额/重复/前置依赖检查。"""
        if self.tool_quota_exhausted_reason is not None:
            return {
                "ok": False,
                "error_code": "tool_quota_exhausted",
                "should_finalize": True,
                "message": (
                    f"本次运行工具配额已用尽（{self.tool_quota_exhausted_reason}），"
                    "请立刻基于现有上下文给出对教师最有用的最终中文回答，不要再尝试调用任何工具。"
                ),
            }

        precondition_block = self.tool_registry.check_write_precondition(tool_name, arguments)
        if precondition_block is not None:
            return precondition_block

        next_total = self.tool_call_count + 1
        if next_total > self.settings.agent_max_tool_calls:
            self.trigger_final_round("已达到本次运行最大工具调用次数")
            return {
                "ok": False,
                "error_code": "max_tool_calls_reached",
                "should_finalize": True,
                "message": (
                    f"已累计调用工具 {self.tool_call_count} 次，达到本次运行上限 "
                    f"{self.settings.agent_max_tool_calls} 次。请立刻基于现有上下文给出最终中文回答，"
                    "不要再尝试调用任何工具。"
                ),
            }

        signature = json.dumps(
            {"tool_name": tool_name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        next_sig_count = self.tool_signature_counts.get(signature, 0) + 1
        if next_sig_count > self.settings.agent_repeated_tool_call_limit:
            return {
                "ok": False,
                "error_code": "repeated_tool_call_blocked",
                "should_finalize": False,
                "message": (
                    f"已对 {tool_name} 用完全相同的参数调用 "
                    f"{self.settings.agent_repeated_tool_call_limit} 次。请改用不同参数继续，"
                    "或直接基于现有上下文给出最终中文回答，不要再用相同参数重试。"
                ),
            }

        self.tool_call_count = next_total
        self.tool_signature_counts[signature] = next_sig_count
        return None

    def build_quota_notice_messages(self, forced_final: bool) -> list[dict[str, Any]]:
        """终结态首轮注入一次性 system 收尾通知。"""
        if not forced_final or self.tool_quota_exhausted_reason is None or self._quota_notice_emitted:
            return []
        self._quota_notice_emitted = True
        return [
            {
                "role": "system",
                "content": (
                    f"[系统通知] 本次运行已进入收尾阶段（{self.tool_quota_exhausted_reason}），"
                    "工具调用已禁用。请立刻基于以上全部上下文，用简体中文 Markdown 给出对教师最有用的最终回答。"
                ),
            }
        ]
