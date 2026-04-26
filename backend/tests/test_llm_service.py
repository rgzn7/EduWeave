"""
@Date: 2026-04-26
@Author: xisy
@Discription: LLM 服务配置行为测试
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.shared.llm import ChatMessage
from app.shared.llm.service import OpenAICompatibleLlmService


class DemoStructuredResponse(BaseModel):
    """测试用结构化响应。"""

    ok: bool = Field(description="是否成功")


class CaptureLlmClient:
    """捕获 LLM 请求载荷的测试客户端。"""

    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}


def build_settings(reasoning_effort: str | None) -> Settings:
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
        llm_reasoning_effort=reasoning_effort,
        milvus_uri="http://127.0.0.1:19530",
        milvus_embedding_dim=4,
    )


def test_structured_output_should_skip_reasoning_effort_when_not_configured() -> None:
    """未配置推理强度时不应传 reasoning_effort。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert client.payload is not None
    assert "reasoning_effort" not in client.payload


def test_structured_output_should_include_reasoning_effort_when_configured() -> None:
    """配置推理强度时应传 reasoning_effort。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings("medium"))

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="返回 ok")],
        response_model=DemoStructuredResponse,
    )

    assert client.payload is not None
    assert client.payload["reasoning_effort"] == "medium"
