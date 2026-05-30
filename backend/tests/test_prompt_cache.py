"""
@Date: 2026-05-30
@Author: xisy
@Discription: 提示词缓存基础设施测试（payload 注入、稳定前缀 cache_control 标记、三协议 cached_tokens 提取）
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.shared.llm import ChatMessage
from app.shared.llm.schemas import LlmUsage
from app.shared.llm.service import OpenAICompatibleLlmService


class DemoStructuredResponse(BaseModel):
    """测试用结构化响应。"""

    ok: bool = Field(description="是否成功")


class CaptureLlmClient:
    """捕获 LLM 请求载荷的测试客户端，可配置自定义 usage 响应。"""

    def __init__(self, usage_payload: dict[str, Any] | None = None) -> None:
        self.payload: dict[str, Any] | None = None
        self.called_method: str | None = None
        self.call_count: int = 0
        base_usage = usage_payload or {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        self.chat_completion_payload: dict[str, Any] = {
            "choices": [{"message": {"content": "{\"ok\": true}"}}],
            "usage": base_usage,
        }
        self.response_payload: dict[str, Any] = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\": true}"}]}],
            "usage": base_usage,
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


def _build_settings(
    *,
    llm_api_format: str = "response",
    llm_prompt_cache_explicit_markers: bool = False,
    llm_prompt_cache_identity_enabled: bool = True,
    llm_prompt_cache_user_enabled: bool = False,
    llm_prompt_cache_key_prefix: str = "eduweave",
) -> Settings:
    """构造测试配置（仅覆盖与 prompt cache 相关的字段）。"""
    return Settings(
        app_load_dotenv=False,
        mysql_host="127.0.0.1",
        mysql_username="root",
        mysql_password="boss1114",
        redis_uri="redis://127.0.0.1:6379/0",
        jwt_secret="test-secret",
        obs_endpoint="https://obs.test.example.com",
        obs_ak="test-ak",
        obs_sk="test-sk",
        obs_bucket="test-bucket",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_api_format=llm_api_format,
        llm_max_retries=0,
        llm_retry_base_seconds=1,
        llm_parse_repair_max_attempts=0,
        llm_prompt_cache_explicit_markers=llm_prompt_cache_explicit_markers,
        llm_prompt_cache_identity_enabled=llm_prompt_cache_identity_enabled,
        llm_prompt_cache_user_enabled=llm_prompt_cache_user_enabled,
        llm_prompt_cache_key_prefix=llm_prompt_cache_key_prefix,
        milvus_uri="http://127.0.0.1:19530",
        milvus_embedding_dim=4,
    )


def _build_stable_messages() -> list[ChatMessage]:
    """构造 3 条稳定前缀（与 lesson_plan 4 消息布局一致）。"""
    return [
        ChatMessage(role="system", content="角色与字段定义提示。"),
        ChatMessage(role="system", content="硬性输出规则提示。"),
        ChatMessage(role="user", content="稳定上下文 JSON 占位。"),
    ]


def test_responses_payload_should_inject_prompt_cache_key_when_enabled() -> None:
    """开启 identity 时 Responses 载荷应注入 prompt_cache_key。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=_build_settings())

    service.generate_structured_output(
        messages=[*_build_stable_messages(), ChatMessage(role="user", content="变量段。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-999",
    )

    assert client.payload is not None
    assert client.payload["prompt_cache_key"] == "eduweave-lesson-batch-999"


def test_chat_payload_should_inject_prompt_cache_key_when_enabled() -> None:
    """开启 identity 时 Chat 载荷也应注入 prompt_cache_key。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=_build_settings(llm_api_format="chat"))

    service.generate_structured_output(
        messages=[*_build_stable_messages(), ChatMessage(role="user", content="变量段 json。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-7",
    )

    assert client.payload is not None
    assert client.payload["prompt_cache_key"] == "eduweave-lesson-batch-7"


def test_payload_should_not_inject_prompt_cache_key_when_identity_disabled() -> None:
    """identity 关闭时不应注入 prompt_cache_key。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=_build_settings(llm_prompt_cache_identity_enabled=False),
    )

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="问题。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-9",
    )

    assert client.payload is not None
    assert "prompt_cache_key" not in client.payload


def test_payload_should_not_inject_prompt_cache_key_when_biz_key_missing() -> None:
    """未传 cache_biz_key 时不注入 prompt_cache_key（即使开关打开）。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=_build_settings())

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="问题。")],
        response_model=DemoStructuredResponse,
    )

    assert client.payload is not None
    assert "prompt_cache_key" not in client.payload


def test_user_field_should_be_injected_only_when_enabled() -> None:
    """user 字段仅在开关开启且 cache_user_id 非空时注入。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=_build_settings(llm_prompt_cache_user_enabled=True),
    )

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="问题。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-2",
        cache_user_id=42,
    )

    assert client.payload is not None
    assert client.payload.get("user") == "eduweave-user-42"


def test_user_field_should_be_omitted_when_switch_off() -> None:
    """user 字段开关关闭时即使传 user_id 也不注入。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=_build_settings())

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="问题。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-2",
        cache_user_id=42,
    )

    assert client.payload is not None
    assert "user" not in client.payload


def test_explicit_markers_should_decorate_responses_stable_prefix() -> None:
    """Responses 端开启 explicit markers 时，第 stable_prefix-1 条 system 应转为含 cache_control 的 input_text 块。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=_build_settings(llm_prompt_cache_explicit_markers=True),
    )

    service.generate_structured_output(
        messages=[*_build_stable_messages(), ChatMessage(role="user", content="变量段。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-1",
        stable_prefix_message_count=3,
    )

    assert client.payload is not None
    input_items = client.payload["input"]
    assert len(input_items) == 4
    # 第 1、2 条 system 仍是字符串 content
    assert input_items[0]["content"] == "角色与字段定义提示。"
    assert input_items[1]["content"] == "硬性输出规则提示。"
    # 第 3 条（锚点）应被转换为含 cache_control 的 input_text 单 block 数组
    anchor = input_items[2]
    assert isinstance(anchor["content"], list)
    assert anchor["content"][0]["type"] == "input_text"
    assert anchor["content"][0]["cache_control"] == {"type": "ephemeral"}
    # 第 4 条变量段保持原样字符串
    assert input_items[3]["content"] == "变量段。"


def test_explicit_markers_should_decorate_chat_stable_prefix_with_text_block_type() -> None:
    """Chat 端 explicit markers 的 block type 应为 text（区别于 Responses 的 input_text）。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=_build_settings(
            llm_api_format="chat",
            llm_prompt_cache_explicit_markers=True,
        ),
    )

    service.generate_structured_output(
        messages=[*_build_stable_messages(), ChatMessage(role="user", content="变量段 json。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-1",
        stable_prefix_message_count=3,
    )

    assert client.payload is not None
    anchor = client.payload["messages"][2]
    assert isinstance(anchor["content"], list)
    assert anchor["content"][0]["type"] == "text"
    assert anchor["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_markers_when_stable_prefix_count_zero() -> None:
    """stable_prefix_message_count=0 时不打 cache_control 标记。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(
        client=client,
        settings=_build_settings(llm_prompt_cache_explicit_markers=True),
    )

    service.generate_structured_output(
        messages=[*_build_stable_messages(), ChatMessage(role="user", content="变量段。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-1",
        stable_prefix_message_count=0,
    )

    assert client.payload is not None
    for item in client.payload["input"]:
        assert isinstance(item["content"], str)


def test_on_usage_callback_should_receive_cached_tokens_from_openai_responses() -> None:
    """on_usage 回调应能从 Responses 协议中拿到 cached_tokens。"""
    client = CaptureLlmClient(
        usage_payload={
            "prompt_tokens": 1500,
            "completion_tokens": 200,
            "total_tokens": 1700,
            "input_tokens_details": {"cached_tokens": 1100},
        },
    )
    service = OpenAICompatibleLlmService(client=client, settings=_build_settings())
    usage_records: list[LlmUsage] = []

    service.generate_structured_output(
        messages=[ChatMessage(role="user", content="问题。")],
        response_model=DemoStructuredResponse,
        cache_biz_key="lesson-batch-1",
        on_usage=usage_records.append,
    )

    assert len(usage_records) == 1
    assert usage_records[0].prompt_tokens == 1500
    assert usage_records[0].cached_tokens == 1100


def test_build_usage_should_extract_cached_tokens_from_three_protocols() -> None:
    """build_usage 应同时兼容 Responses / Chat / Anthropic 三种协议字段。"""
    responses_usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "total_tokens": 1100,
        "input_tokens_details": {"cached_tokens": 700},
    }
    chat_usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "total_tokens": 1100,
        "prompt_tokens_details": {"cached_tokens": 500},
    }
    anthropic_usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "total_tokens": 1100,
        "cache_read_input_tokens": 800,
    }

    assert OpenAICompatibleLlmService.build_usage({"usage": responses_usage}).cached_tokens == 700
    assert OpenAICompatibleLlmService.build_usage({"usage": chat_usage}).cached_tokens == 500
    assert OpenAICompatibleLlmService.build_usage({"usage": anthropic_usage}).cached_tokens == 800
    assert OpenAICompatibleLlmService.build_usage({"usage": {}}).cached_tokens == 0
