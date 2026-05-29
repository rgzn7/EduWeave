"""
@Date: 2026-05-29
@Author: xisy
@Discription: 端到端验证新版 AgentLLMRunner（Responses 协议）：
              第 1 轮拿到带真实参数的 function_call，回灌 function_call_output 后，
              第 2 轮应产出最终文本。重点验证 packyapi 对 Responses 工具调用回灌的兼容性。
"""

from __future__ import annotations

import json

from app.modules.agent.llm_runner import AgentLLMRunner

# 复用真实工具定义（Chat 形态，runner 内部会转 Responses 扁平形态）
from app.modules.agent.tools import TOOL_SCHEMAS

SYSTEM = {"role": "system", "content": "你是备课助手。涉及教材知识时必须先调用 search_textbook 检索，再回答。"}
USER = {"role": "user", "content": "讲讲三年级英语里的名词复数表达知识点，先检索教材。"}


def main() -> None:
    runner = AgentLLMRunner()

    # ---- 第 1 轮：期望返回 function_call(search_textbook, 带真实 query) ----
    conversation = [SYSTEM, USER]
    result1 = runner.run_chat(messages=conversation, tools=TOOL_SCHEMAS, tool_choice="auto")
    print("== 第 1 轮 ==")
    print("content:", (result1.content or "")[:120])
    print("tool_calls:", json.dumps(result1.tool_calls, ensure_ascii=False))

    if not result1.tool_calls:
        print("!! 第 1 轮未触发工具调用，无法继续验证回灌")
        return

    tc = result1.tool_calls[0]
    args = AgentLLMRunner.parse_tool_arguments(tc.get("arguments"))
    print("解析出的参数:", args, "=> query 非空?", bool(args.get("query")))

    # ---- 回灌 function_call + function_call_output，进行第 2 轮 ----
    if (result1.content or "").strip():
        conversation.append({"role": "assistant", "content": result1.content})
    conversation.append(
        {
            "type": "function_call",
            "call_id": tc.get("call_id") or "",
            "name": tc.get("name") or "",
            "arguments": tc.get("arguments") or "{}",
        }
    )
    fake_tool_result = {
        "ok": True,
        "query": args.get("query"),
        "count": 1,
        "hits": [{"rank": 1, "page_start": 12, "page_end": 13, "content": "名词复数：一般加 -s，如 book->books；以 s/x/ch/sh 结尾加 -es。"}],
    }
    conversation.append(
        {
            "type": "function_call_output",
            "call_id": tc.get("call_id") or "",
            "output": json.dumps(fake_tool_result, ensure_ascii=False),
        }
    )
    result2 = runner.run_chat(messages=conversation, tools=TOOL_SCHEMAS, tool_choice="auto")
    print("\n== 第 2 轮 ==")
    print("tool_calls:", json.dumps(result2.tool_calls, ensure_ascii=False))
    print("最终文本(前 300):", (result2.content or "")[:300])


if __name__ == "__main__":
    main()
