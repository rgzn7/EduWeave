"""
@Date: 2026-04-14
@Author: xisy
@Discription: OpenAI 兼容 LLM 请求响应模型
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """统一聊天消息结构。

    content 支持两种形态：
    - str：纯文本消息（默认，零行为变化）。
    - list[dict]：中性多模态 content part 列表，约定形态
      {"type": "text", "text": str} 与 {"type": "image", "data_url": str}，
      不耦合 chat/responses 厂商格式，翻译下沉到 service 层。
    """

    role: str = Field(description="消息角色", examples=["system"])
    content: str | list[dict[str, Any]] = Field(
        description="消息内容（纯文本或中性多模态 part 列表）",
        examples=["你是一个知识抽取助手。"],
    )

    @field_validator("role")
    @classmethod
    def validate_non_blank_role(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("消息字段不能为空")
        return normalized_value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if isinstance(value, str):
            normalized_value = value.strip()
            if not normalized_value:
                raise ValueError("消息字段不能为空")
            return normalized_value
        if not value:
            raise ValueError("消息字段不能为空")
        return value


class LlmUsage(BaseModel):
    """聊天调用 token 使用量。"""

    prompt_tokens: int = Field(default=0, description="提示词 token 数")
    completion_tokens: int = Field(default=0, description="输出 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")
    cached_tokens: int = Field(default=0, description="命中提示词缓存的 token 数")


class EmbeddingUsage(BaseModel):
    """Embedding 调用 token 使用量。"""

    prompt_tokens: int = Field(default=0, description="输入 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")
