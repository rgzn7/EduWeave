"""
@Date: 2026-05-17
@Author: xisy
@Discription: LLM 多模态消息结构、格式翻译、修复与证据图片加载测试
"""

from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.shared.llm import ChatMessage, load_evidence_image_data_urls
from app.shared.llm.service import OpenAICompatibleLlmService
from tests.test_llm_service import CaptureLlmClient, build_settings


class DemoStructuredResponse(BaseModel):
    """测试用结构化响应。"""

    ok: bool = Field(description="是否成功")


def _image_user_message() -> ChatMessage:
    return ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "请返回 json"},
            {"type": "image", "data_url": "data:image/png;base64,AAA"},
        ],
    )


# --- ChatMessage 结构 ---


def test_chat_message_accepts_list_content() -> None:
    """content 支持中性 part 列表。"""
    message = _image_user_message()
    assert isinstance(message.content, list)
    assert message.content[1]["type"] == "image"


def test_chat_message_rejects_empty_list_content() -> None:
    """空列表 content 应被校验拒绝。"""
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content=[])


def test_chat_message_rejects_blank_str_content() -> None:
    """空白字符串 content 仍应被拒绝。"""
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="   ")


# --- 格式翻译 ---


def test_translate_message_str_keeps_model_dump() -> None:
    """str content 翻译后与 model_dump 完全一致（零行为变化）。"""
    message = ChatMessage(role="user", content="返回 ok")
    assert OpenAICompatibleLlmService._translate_message(message, "chat") == {
        "role": "user",
        "content": "返回 ok",
    }
    assert OpenAICompatibleLlmService._translate_message(message, "responses") == {
        "role": "user",
        "content": "返回 ok",
    }


def test_translate_message_chat_image_block() -> None:
    """chat 格式图片翻译为 image_url 结构。"""
    translated = OpenAICompatibleLlmService._translate_message(_image_user_message(), "chat")
    assert translated["content"][0] == {"type": "text", "text": "请返回 json"}
    assert translated["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAA", "detail": "auto"},
    }


def test_translate_message_responses_image_block() -> None:
    """responses 格式图片翻译为 input_image 结构。"""
    translated = OpenAICompatibleLlmService._translate_message(_image_user_message(), "responses")
    assert translated["content"][0] == {"type": "input_text", "text": "请返回 json"}
    assert translated["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,AAA",
        "detail": "auto",
    }


def test_message_text_extracts_only_text_parts() -> None:
    """_message_text 仅提取 text part，丢弃图片。"""
    assert OpenAICompatibleLlmService._message_text(_image_user_message()) == "请返回 json"
    assert OpenAICompatibleLlmService._message_text(ChatMessage(role="user", content="纯文本")) == "纯文本"


# --- service 集成：两种格式都带图 ---


def test_chat_payload_contains_image_block() -> None:
    """chat 格式下含图消息应产出 image_url part，并因已含 json 不追加提示。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None, llm_api_format="chat"))

    service.generate_structured_output(
        messages=[_image_user_message()],
        response_model=DemoStructuredResponse,
    )

    assert client.called_method == "chat"
    messages = client.payload["messages"]
    assert len(messages) == 1
    assert messages[0]["content"][1]["type"] == "image_url"


def test_responses_payload_contains_image_block() -> None:
    """responses 格式下含图消息应产出 input_image part。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None))

    service.generate_structured_output(
        messages=[_image_user_message()],
        response_model=DemoStructuredResponse,
    )

    assert client.called_method == "response"
    assert client.payload["input"][0]["content"][1]["type"] == "input_image"


def test_chat_json_hint_appended_for_image_message_without_json() -> None:
    """含图但无 json 关键字时仍应兜底追加 JSON 提示消息。"""
    client = CaptureLlmClient()
    service = OpenAICompatibleLlmService(client=client, settings=build_settings(None, llm_api_format="chat"))

    message = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "请生成教案"},
            {"type": "image", "data_url": "data:image/png;base64,AAA"},
        ],
    )
    service.generate_structured_output(messages=[message], response_model=DemoStructuredResponse)

    messages = client.payload["messages"]
    assert messages[-1] == {"role": "user", "content": "请严格以 JSON 对象格式输出最终结果。"}


# --- 修复消息只保留文本 ---


def test_repair_messages_drop_images() -> None:
    """JSON 修复上下文应只含 text，不含图片 data_url。"""
    service = OpenAICompatibleLlmService(client=CaptureLlmClient(), settings=build_settings(None))
    from app.core.exceptions import AppException, BusinessErrorCode

    repair_messages = service._build_repair_messages(
        original_messages=[_image_user_message()],
        response_model=DemoStructuredResponse,
        invalid_text="bad",
        parse_error=AppException(BusinessErrorCode.LLM_RESULT_INVALID, "bad"),
        repair_attempt=1,
    )
    joined = "\n".join(m.content for m in repair_messages)
    assert "请返回 json" in joined
    assert "data:image/png;base64,AAA" not in joined


# --- 证据图片加载器 ---


class _FakeStorage:
    def __init__(self, mapping: dict[str, bytes], fail_keys: set[str] | None = None) -> None:
        self._mapping = mapping
        self._fail_keys = fail_keys or set()

    def download_bytes(self, object_key: str) -> bytes:
        if object_key in self._fail_keys:
            raise RuntimeError("download failed")
        return self._mapping[object_key]


def test_loader_dedup_and_cap() -> None:
    """按 file_object_id 去重并截断到 max_images。"""
    assets = [
        (1, "k1", "image/png", "png"),
        (1, "k1", "image/png", "png"),
        (2, "k2", "image/jpeg", "jpg"),
        (3, "k3", "image/png", "png"),
    ]
    storage = _FakeStorage({"k1": b"a", "k2": b"b", "k3": b"c"})
    urls = load_evidence_image_data_urls(assets=assets, max_images=2, storage_client=storage)
    assert len(urls) == 2
    assert urls[0].startswith("data:image/png;base64,")
    assert urls[1].startswith("data:image/jpeg;base64,")


def test_loader_skips_failed_download() -> None:
    """单图下载失败仅跳过，不影响其余图片。"""
    assets = [(1, "k1", "image/png", "png"), (2, "k2", "image/png", "png")]
    storage = _FakeStorage({"k2": b"ok"}, fail_keys={"k1"})
    urls = load_evidence_image_data_urls(assets=assets, max_images=6, storage_client=storage)
    assert len(urls) == 1


def test_loader_mime_fallback_by_ext() -> None:
    """mime_type 缺失时按扩展名兜底。"""
    assets = [(1, "k1", None, "jpeg")]
    storage = _FakeStorage({"k1": b"x"})
    urls = load_evidence_image_data_urls(assets=assets, max_images=6, storage_client=storage)
    assert urls[0].startswith("data:image/jpeg;base64,")


def test_loader_empty_inputs() -> None:
    """无资产或上限为 0 时返回空列表。"""
    assert load_evidence_image_data_urls(assets=[], max_images=6, storage_client=_FakeStorage({})) == []
    assert (
        load_evidence_image_data_urls(
            assets=[(1, "k1", "image/png", "png")], max_images=0, storage_client=_FakeStorage({"k1": b"x"})
        )
        == []
    )
