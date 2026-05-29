"""
@Date: 2026-05-29
@Author: xisy
@Discription: 探针脚本：对比 chat 流式与 responses 流式下，gpt-5.5(@packyapi) 工具调用参数的下发情况，
              用于定位「检索工具参数恒为空 {}」的根因。仅做一次最小调用，不写库。
"""

from __future__ import annotations

import json

import httpx

from app.core.config import get_settings

# 最小工具：要求必填 query，便于观察模型是否真把参数下发回来
TOOL_NAME = "search_textbook"
TOOL_DESC = "在教材语义块中检索，用于回答教材知识问题。"
USER_PROMPT = "请调用 search_textbook 检索「复数表达」这个知识点。"


def _chat_payload(model: str, reasoning_effort: str | None) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": USER_PROMPT}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": TOOL_DESC,
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "检索关键词"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def _responses_payload(model: str, reasoning_effort: str | None) -> dict:
    payload = {
        "model": model,
        "input": [{"role": "user", "content": USER_PROMPT}],
        "tools": [
            {
                "type": "function",
                "name": TOOL_NAME,
                "description": TOOL_DESC,
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "检索关键词"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def _iter_sse(response: httpx.Response):
    event_type = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if data_lines:
                yield event_type, "\n".join(data_lines)
            event_type = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield event_type, "\n".join(data_lines)


def probe_chat(settings) -> None:
    print("\n========== [CHAT /chat/completions 流式] ==========")
    url = f"{settings.llm_api_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = _chat_payload(settings.llm_model, settings.llm_reasoning_effort)
    # 按 index 累积 tool_calls.arguments 分片（复刻 AgentLLMRunner 的拼接逻辑）
    acc: dict[int, dict[str, str]] = {}
    raw_arg_chunks: list[str] = []
    with httpx.Client(timeout=float(settings.llm_timeout_seconds)) as client:
        with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.is_error:
                resp.read()
                print("HTTP ERROR", resp.status_code, resp.text[:500])
                return
            for _event, data_text in _iter_sse(resp):
                if data_text == "[DONE]":
                    break
                try:
                    data = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta") or {}
                for pos, tc in enumerate(delta.get("tool_calls") or []):
                    idx = tc.get("index", pos)
                    slot = acc.setdefault(idx, {"name": "", "arguments": ""})
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if isinstance(fn.get("arguments"), str):
                        slot["arguments"] += fn["arguments"]
                        raw_arg_chunks.append(repr(fn["arguments"]))
    print("装配出的 tool_calls：", json.dumps(acc, ensure_ascii=False))
    print("arguments 原始分片：", raw_arg_chunks or "(没有收到任何 arguments 分片)")


def probe_responses(settings) -> None:
    print("\n========== [RESPONSES /responses 流式] ==========")
    url = f"{settings.llm_api_base_url}/responses"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = _responses_payload(settings.llm_model, settings.llm_reasoning_effort)
    output_items: list[dict] = []
    with httpx.Client(timeout=float(settings.llm_timeout_seconds)) as client:
        with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.is_error:
                resp.read()
                print("HTTP ERROR", resp.status_code, resp.text[:500])
                return
            for event, data_text in _iter_sse(resp):
                if data_text == "[DONE]":
                    break
                try:
                    data = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                etype = event or data.get("type")
                if etype == "response.output_item.done" and isinstance(data.get("item"), dict):
                    output_items.append(data["item"])
                elif etype == "response.completed" and isinstance(data.get("response"), dict):
                    out = data["response"].get("output")
                    if isinstance(out, list):
                        output_items = out
    fcs = [it for it in output_items if it.get("type") == "function_call"]
    print("function_call 项：", json.dumps(fcs, ensure_ascii=False))


def main() -> None:
    settings = get_settings()
    print("model =", settings.llm_model, "| base =", settings.llm_api_base_url,
          "| reasoning_effort =", settings.llm_reasoning_effort, "| api_format =", settings.llm_api_format)
    probe_chat(settings)
    probe_responses(settings)


if __name__ == "__main__":
    main()
