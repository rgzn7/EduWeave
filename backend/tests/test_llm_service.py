"""
@Date: 2026-05-28
@Author: xisy
@Discription: LLM 服务配置、重试、流式与解析-修复行为测试
"""

import json
import time
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.llm import ChatMessage
from app.shared.llm.client import OpenAICompatibleLlmClient
from app.shared.llm.service import OpenAICompatibleLlmService


class DemoStructuredResponse(BaseModel):
    """测试用结构化响应。"""

    ok: bool = Field(description="是否成功")


class CaptureLlmClient:
    """捕获 LLM 请求载荷的测试客户端。"""

    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.called_method: str | None = None
        self.call_count: int = 0
        self.chat_completion_payload: dict[str, Any] = {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        self.response_payload: dict[str, Any] = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": true}"}]}]
        }

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        self.called_method = "chat"
        self.call_count += 1
        return self.chat_completion_payload

    def create_response_stream(self, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        self.payload = payload
        self.called_method = "response"
        self.call_count += 1
        return None, self.response_payload


def build_settings(
    reasoning_effort: str | None,
    llm_api_format: str = "response",
    *,
    llm_max_retries: int = 2,
    llm_retry_base_seconds: int = 1,
    llm_stream_error_detail_max_chars: int = 4096,
    llm_parse_repair_max_attempts: int = 2,
) -> Settings:
    """构造测试配置。"""
    return Settings(
        app_load_dotenv=False,
        mysql_host="127.0.0.1",
        mysql_user="root",
        mysql_password="boss1114",
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret="test-secret",
        obs_endpoint="https://obs.test.example.com",
        obs_ak="test-ak",
        obs_sk="test-sk",
        obs_bucket="test-bucket",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_api_format=llm_api_format,
        llm_reasoning_effort=reasoning_effort,
        llm_max_retries=llm_max_retries,
        llm_retry_base_seconds=llm_retry_base_seconds,
        llm_stream_error_detail_max_chars=llm_stream_error_detail_max_chars,
        llm_parse_repair_max_attempts=llm_parse_repair_max_attempts,
        milvus_uri="http://127.0.0.1:19530",
        milvus_embedding_dim=4,
    )


def _build_real_client(handler: Any, settings: Settings) -> OpenAICompatibleLlmClient:
    """用 httpx.MockTransport 构造可控的真实客户端。"""
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleLlmClient(settings=settings, http_client=httpx.Client(transport=transport, timeout=5))


def _sse_event(event: str, data_obj: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data_obj)}\n\n".encode()


def _sse_data(data_obj: Any) -> bytes:
    """构造仅含 data 行的 SSE 块（PackyAPI chat 流式无 event 行）。"""
    return f"data: {json.dumps(data_obj)}\n\n".encode()


def _chat_chunk(content: str) -> dict[str, Any]:
    """构造 chat.completion.chunk 形态的单帧。"""
    return {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
    }


def test_structured_output_should_skip_reasoning_effort_when_not_configured() -> None:
    """未配置推理强度时不应传 reasoning。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert client.payload is not None
    assert client.called_method == "response"
    assert "response_format" not in client.payload
    assert "messages" not in client.payload
    assert "reasoning_effort" not in client.payload
    assert "reasoning" not in client.payload
    assert client.payload["input"] == [{"role": "user", "content": "返回 ok"}]
    format_payload = client.payload["text"]["format"]
    assert format_payload["type"] == "json_schema"
    assert format_payload["name"] == "DemoStructuredResponse"
    assert format_payload["schema"]["properties"]["ok"]["type"] == "boolean"
    assert format_payload["strict"] is False


def test_structured_output_should_include_reasoning_effort_when_configured() -> None:
    """配置推理强度时应传 Responses reasoning.effort。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings("medium"))

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert client.payload is not None
    assert "reasoning_effort" not in client.payload
    assert client.payload["reasoning"]["effort"] == "medium"


def test_structured_output_should_extract_output_text() -> None:
    """应从 Responses 标准 output_text 内容中提取 JSON。"""
    client = CaptureLlmClient()
    client.response_payload = {"output_text": "{\"ok\": true}"}
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_structured_output_should_extract_content_output_text() -> None:
    """应从 Responses content.output_text 内容中提取 JSON。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_structured_output_should_call_chat_completion_when_configured() -> None:
    """配置 chat 格式时应调用 Chat Completions 并解析 JSON。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None, llm_api_format="chat"))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert client.payload is not None
    assert client.called_method == "chat"
    assert "input" not in client.payload
    assert "text" not in client.payload
    assert "reasoning" not in client.payload
    assert "reasoning_effort" not in client.payload
    assert client.payload["messages"] == [
        {"role": "user", "content": "返回 ok"},
        {"role": "user", "content": "请严格以 JSON 对象格式输出最终结果。"},
    ]
    assert client.payload["response_format"] == {"type": "json_object"}


def test_structured_output_should_not_append_json_hint_when_present() -> None:
    """原始 user 消息已包含 JSON 要求时不应重复追加提示。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None, llm_api_format="chat"))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="请返回 JSON：{\"ok\": true}")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert client.payload is not None
    assert client.payload["messages"] == [{"role": "user", "content": "请返回 JSON：{\"ok\": true}"}]


def test_structured_output_should_extract_json_from_markdown_text() -> None:
    """应兼容模型返回 Markdown JSON 代码块。"""
    client = CaptureLlmClient()
    client.response_payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "```json\n{\"ok\": true}\n```"}],
            }
        ]
    }
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_structured_output_should_raise_when_schema_validation_failed() -> None:
    """当输出无法通过 Pydantic 校验且无修复机会时应抛业务异常。"""
    client = CaptureLlmClient()
    client.response_payload = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": null}"}]}]
    }
    service = OpenAICompatibleLlmService(
        client=client,
        settings=build_settings(None, llm_parse_repair_max_attempts=0),
    )

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.code == BusinessErrorCode.LLM_RESULT_INVALID
    assert exc_info.value.details is not None
    assert "errors" in exc_info.value.details


def test_chat_completion_retries_transient_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat Completions 遇到 503 应重试并最终成功。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    settings = build_settings(None, llm_api_format="chat", llm_max_retries=2)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 json ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert calls["n"] == 2


def test_chat_completion_raises_after_retry_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """传输层重试耗尽后应抛 LLM_REQUEST_FAILED。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout")

    settings = build_settings(None, llm_api_format="chat", llm_max_retries=1)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 json ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.code == BusinessErrorCode.LLM_REQUEST_FAILED


def test_structured_output_retries_when_text_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 成功返回但无文本时应重发原始调用。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    class MissingTextClient:
        def __init__(self) -> None:
            self.call_count = 0

        def create_response_stream(self, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
            self.call_count += 1
            if self.call_count == 1:
                return None, {"status": "incomplete", "output": []}
            return None, {"output_text": "{\"ok\": true}"}

    client = MissingTextClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None, llm_max_retries=2))

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert client.call_count == 2


def test_structured_output_repairs_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """首次返回非法 JSON，触发修复循环并在第二次成功。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    class RepairClient:
        def __init__(self) -> None:
            self.call_count = 0

        def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            self.call_count += 1
            if self.call_count == 1:
                return {"choices": [{"message": {"content": "这不是 JSON"}}]}
            return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}

    client = RepairClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=build_settings(None, llm_api_format="chat", llm_parse_repair_max_attempts=2),
    )

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 json ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert client.call_count == 2


def test_structured_output_raises_after_repair_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """修复次数耗尽后仍非法应抛 LLM_RESULT_INVALID。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    class AlwaysInvalidClient:
        def __init__(self) -> None:
            self.call_count = 0

        def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            self.call_count += 1
            return {"choices": [{"message": {"content": "仍然不是 JSON"}}]}

    client = AlwaysInvalidClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=build_settings(None, llm_api_format="chat", llm_parse_repair_max_attempts=1),
    )

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 json ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.code == BusinessErrorCode.LLM_RESULT_INVALID
    assert client.call_count == 2


def test_response_stream_accumulates_delta() -> None:
    """Responses 流式应累积 output_text.delta 并在 [DONE] 结束。"""
    sse = (
        _sse_event("response.output_text.delta", {"delta": "{\"ok\": "})
        + _sse_event("response.output_text.delta", {"delta": "true}"})
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_response_stream_should_read_completed_after_output_text_done() -> None:
    """Responses 流式在 output_text.done 后仍应读取 completed 里的 usage。"""
    usage_payload = {
        "input_tokens": 100,
        "output_tokens": 8,
        "total_tokens": 108,
        "input_tokens_details": {"cached_tokens": 80},
    }
    sse = (
        _sse_event("response.output_text.done", {"text": "{\"ok\": true}"})
        + _sse_event(
            "response.completed",
            {
                "response": {
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": true}"}]}],
                    "usage": usage_payload,
                }
            },
        )
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)
    usage_records = []

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
        on_usage=usage_records.append,
    )

    assert result.ok is True
    assert len(usage_records) == 1
    assert usage_records[0].prompt_tokens == 100
    assert usage_records[0].cached_tokens == 80


def test_response_stream_raises_on_error_event() -> None:
    """Responses 流式错误事件应转换为业务异常。"""
    sse = _sse_event("response.failed", {"error": {"message": "boom"}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None, llm_max_retries=0)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.code == BusinessErrorCode.LLM_REQUEST_FAILED
    assert exc_info.value.details == {
        "api_format": "responses",
        "transport": "stream",
        "event_type": "response.failed",
        "retryable": True,
        "error": {"message": "boom"},
    }


def test_response_stream_retries_sse_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Responses 流式 200+错误事件应在单次请求层重试。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}
    failed_sse = _sse_event("response.failed", {"error": {"message": "boom"}})
    success_sse = (
        _sse_event("response.output_text.delta", {"delta": "{\"ok\": true}"})
        + _sse_event("response.completed", {"response": {}})
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content = failed_sse if calls["n"] == 1 else success_sse
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

    settings = build_settings(None, llm_max_retries=2)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert calls["n"] == 2


def test_response_stream_should_preserve_safe_incomplete_detail() -> None:
    """Responses incomplete 事件应保留安全原因字段。"""
    sse = _sse_event(
        "response.incomplete",
        {"response": {"id": "resp_1", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None, llm_max_retries=0)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.details == {
        "api_format": "responses",
        "transport": "stream",
        "event_type": "response.incomplete",
        "retryable": True,
        "response": {"id": "resp_1", "status": "incomplete"},
        "incomplete_details": {"reason": "max_output_tokens"},
    }


def test_response_stream_should_not_retry_non_retryable_sse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """不可恢复的 Responses 流式错误不应进入请求层重试。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}
    failed_sse = _sse_event(
        "response.failed",
        {"error": {"type": "invalid_request_error", "code": "context_length_exceeded", "message": "too long"}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=failed_sse)

    settings = build_settings(None, llm_max_retries=2)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )

    assert calls["n"] == 1
    assert exc_info.value.details["retryable"] is False


def test_response_stream_should_truncate_safe_error_detail() -> None:
    """流式错误详情应按配置截断。"""
    sse = _sse_event("response.failed", {"error": {"message": "x" * 20}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None, llm_max_retries=0, llm_stream_error_detail_max_chars=8)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.details["error"]["message"] == "x" * 8


def test_chat_completion_stream_accumulates_delta() -> None:
    """Chat Completions 流式 chunk 应累积 delta.content 并在 [DONE] 结束。"""
    sse = (
        _sse_data(_chat_chunk("{\"ok\": "))
        + _sse_data(_chat_chunk("true}"))
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None, llm_api_format="chat")
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 json ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_chat_completion_stream_raises_on_error_event() -> None:
    """Chat Completions 流式 200+error 体应转换为业务异常。"""
    sse = _sse_data({"error": {"message": "boom"}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None, llm_api_format="chat", llm_max_retries=0)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    with pytest.raises(AppException) as exc_info:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 json ok")],
            response_model=DemoStructuredResponse,
        )

    assert exc_info.value.code == BusinessErrorCode.LLM_REQUEST_FAILED


def test_chat_completion_stream_retries_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat Completions 流式 200+error 体应在单次请求层重试。"""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}
    failed_sse = _sse_data({"error": {"message": "boom"}})
    success_sse = (
        _sse_data(_chat_chunk("{\"ok\": "))
        + _sse_data(_chat_chunk("true}"))
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content = failed_sse if calls["n"] == 1 else success_sse
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

    settings = build_settings(None, llm_api_format="chat", llm_max_retries=2)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 json ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
    assert calls["n"] == 2


def test_chat_completion_non_stream_json_fallback() -> None:
    """网关忽略 stream 仍返回非流式 JSON 时应双模回退解析。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    settings = build_settings(None, llm_api_format="chat")
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 json ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True


def test_response_stream_accepts_chat_style_chunks() -> None:
    """LLM_API_FORMAT=response 下 PackyAPI 中继回 chat chunk 也应能拼出文本。"""
    sse = (
        _sse_data(_chat_chunk("{\"ok\": "))
        + _sse_data(_chat_chunk("true}"))
        + b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    settings = build_settings(None)
    service = OpenAICompatibleLlmService(client=_build_real_client(handler, settings), settings=settings)

    result = service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert result.ok is True
