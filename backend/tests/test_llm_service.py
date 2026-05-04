"""
@Date: 2026-05-04
@Author: xisy
@Discription: LLM 服务配置行为测试
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.llm import ChatMessage
from app.shared.llm.service import OpenAICompatibleLlmService


class DemoStructuredResponse(BaseModel):
    """测试用结构化响应。"""

    ok: bool = Field(description="是否成功")


class CaptureLlmClient:
    """捕获 LLM 请求载荷的测试客户端。"""

    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.called_method: str | None = None
        self.chat_completion_payload: dict[str, Any] = {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        self.response_payload: dict[str, Any] = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": true}"}]}]
        }

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        self.called_method = "chat"
        return self.chat_completion_payload

    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        self.called_method = "response"
        return self.response_payload


def build_settings(reasoning_effort: str | None, llm_api_format: str = "response") -> Settings:
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
        llm_model="test-model",
        llm_api_format=llm_api_format,
        llm_reasoning_effort=reasoning_effort,
        milvus_uri="http://127.0.0.1:19530",
        milvus_embedding_dim=4,
    )


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
    """当 Responses 输出无法通过 Pydantic 校验时应抛业务异常。"""
    client = CaptureLlmClient()
    client.response_payload = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": null}"}]}]
    }
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    try:
        service.generate_structured_output(
            messages=[ChatMessage(role="user", content="返回 ok")],
            response_model=DemoStructuredResponse,
        )
    except AppException as exc:
        assert exc.code == BusinessErrorCode.LLM_RESULT_INVALID
        assert exc.details is not None
        assert "errors" in exc.details
    else:
        raise AssertionError("结构化输出校验失败时应抛出 AppException")
