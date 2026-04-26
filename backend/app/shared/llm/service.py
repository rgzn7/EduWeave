"""
@Date: 2026-04-14
@Author: xisy
@Discription: OpenAI 兼容 LLM 业务封装
"""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.llm.client import OpenAICompatibleEmbeddingClient, OpenAICompatibleLlmClient
from app.shared.llm.schemas import ChatMessage, EmbeddingUsage, LlmUsage


class OpenAICompatibleLlmService:
    """结构化聊天输出服务。"""

    def __init__(
        self,
        client: OpenAICompatibleLlmClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleLlmClient(self.settings)

    def generate_structured_output(
        self,
        *,
        messages: list[ChatMessage],
        response_model: type[BaseModel],
        temperature: float = 0.2,
    ) -> BaseModel:
        """生成结构化 JSON 输出并解析为指定模型。"""
        payload = {
            "model": self.settings.llm_model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [message.model_dump() for message in messages],
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        result = self.client.create_chat_completion(payload)
        content = self._extract_message_content(result)
        parsed_json = self._extract_json_payload(content)
        try:
            return response_model.model_validate(parsed_json)
        except ValidationError as exc:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回结果结构不符合预期",
                {"errors": exc.errors(), "payload": parsed_json},
            ) from exc

    @staticmethod
    def _extract_message_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回结果缺少 choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            joined_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    joined_parts.append(str(item.get("text") or ""))
            content = "\n".join(item for item in joined_parts if item)
        if not isinstance(content, str) or not content.strip():
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回结果缺少文本内容")
        return content.strip()

    @staticmethod
    def _extract_json_payload(content: str) -> dict[str, Any]:
        normalized_content = content.strip()
        if normalized_content.startswith("```"):
            normalized_content = normalized_content.strip("`")
            if normalized_content.startswith("json"):
                normalized_content = normalized_content[4:].strip()
        try:
            parsed_payload = json.loads(normalized_content)
        except json.JSONDecodeError:
            start_index = normalized_content.find("{")
            end_index = normalized_content.rfind("}")
            if start_index < 0 or end_index <= start_index:
                raise AppException(
                    BusinessErrorCode.LLM_RESULT_INVALID,
                    "LLM 返回结果不是合法 JSON",
                    {"content": content},
                )
            try:
                parsed_payload = json.loads(normalized_content[start_index : end_index + 1])
            except json.JSONDecodeError as exc:
                raise AppException(
                    BusinessErrorCode.LLM_RESULT_INVALID,
                    "LLM 返回结果不是合法 JSON",
                    {"content": content},
                ) from exc

        if not isinstance(parsed_payload, dict):
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回结果必须为 JSON 对象",
                {"payload_type": type(parsed_payload).__name__},
            )
        return parsed_payload

    @staticmethod
    def build_usage(payload: dict[str, Any]) -> LlmUsage:
        """从原始响应中提取使用量。"""
        usage = payload.get("usage") or {}
        return LlmUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )


class OpenAICompatibleEmbeddingService:
    """Embedding 能力服务。"""

    def __init__(
        self,
        client: OpenAICompatibleEmbeddingClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleEmbeddingClient(self.settings)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。"""
        normalized_texts = [text.strip() for text in texts if text and text.strip()]
        if not normalized_texts:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "Embedding 输入文本不能为空")
        payload = {
            "model": self.settings.embedding_model,
            "input": normalized_texts,
        }
        result = self.client.create_embeddings(payload)
        data = result.get("data") or []
        if len(data) != len(normalized_texts):
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "Embedding 返回结果数量与输入不一致",
                {"input_count": len(normalized_texts), "result_count": len(data)},
            )

        embeddings: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                raise AppException(
                    BusinessErrorCode.LLM_RESULT_INVALID,
                    "Embedding 返回结果缺少有效向量",
                    {"item": item},
                )
            embeddings.append([float(value) for value in embedding])
        return embeddings

    @staticmethod
    def build_usage(payload: dict[str, Any]) -> EmbeddingUsage:
        """从 Embedding 原始响应中提取使用量。"""
        usage = payload.get("usage") or {}
        return EmbeddingUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )
