"""
@Date: 2026-04-14
@Author: xisy
@Discription: OpenAI 兼容 LLM 请求响应模型
"""

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """统一聊天消息结构。"""

    role: str = Field(description="消息角色", examples=["system"])
    content: str = Field(description="消息内容", min_length=1, examples=["你是一个知识抽取助手。"])

    @field_validator("role", "content")
    @classmethod
    def validate_non_blank_string(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("消息字段不能为空")
        return normalized_value


class LlmUsage(BaseModel):
    """聊天调用 token 使用量。"""

    prompt_tokens: int = Field(default=0, description="提示词 token 数")
    completion_tokens: int = Field(default=0, description="输出 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")


class EmbeddingUsage(BaseModel):
    """Embedding 调用 token 使用量。"""

    prompt_tokens: int = Field(default=0, description="输入 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")
