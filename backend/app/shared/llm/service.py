"""
@Date: 2026-05-04
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
    """OpenAI 兼容结构化输出服务。"""

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
        if self.settings.llm_api_format == "chat":
            payload = self._build_chat_completion_payload(messages=messages, temperature=temperature)
            result = self.client.create_chat_completion(payload)
            content = self._extract_chat_completion_content(result)
            return self._validate_structured_payload(content=content, response_model=response_model)

        payload = self._build_response_payload(messages=messages, response_model=response_model, temperature=temperature)
        result = self.client.create_response(payload)
        content = self._extract_response_content(result)
        return self._validate_structured_payload(content=content, response_model=response_model)

    def _build_response_payload(
        self,
        *,
        messages: list[ChatMessage],
        response_model: type[BaseModel],
        temperature: float,
    ) -> dict[str, Any]:
        """构造 OpenAI Responses 结构化请求。"""
        # reasoning 类模型（如 gpt-5 系列）不接受 temperature，仅接受 reasoning.effort；
        # 若配置中显式给出 reasoning_effort，则忽略 temperature 以避免上游 400。
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "input": [message.model_dump() for message in messages],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                    "strict": False,
                }
            },
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning"] = {"effort": self.settings.llm_reasoning_effort}
        else:
            payload["temperature"] = temperature
        return payload

    def _build_chat_completion_payload(
        self,
        *,
        messages: list[ChatMessage],
        temperature: float,
    ) -> dict[str, Any]:
        """构造 Chat Completions 兼容结构化请求。"""
        # reasoning 类模型（如 gpt-5 系列）不接受 temperature，仅接受 reasoning_effort
        message_payloads = [message.model_dump() for message in messages]
        # OpenAI 在使用 response_format=json_object 时要求 user 消息中出现 "json" 字样，
        # 否则会以 invalid_request_error 拒绝；此处兜底追加提示，避免上游 prompt 漏写。
        if not any(
            item.get("role") == "user" and "json" in str(item.get("content") or "").lower()
            for item in message_payloads
        ):
            message_payloads.append({"role": "user", "content": "请严格以 JSON 对象格式输出最终结果。"})
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "response_format": {"type": "json_object"},
            "messages": message_payloads,
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        else:
            payload["temperature"] = temperature
        return payload

    @staticmethod
    def _validate_structured_payload(*, content: str, response_model: type[BaseModel]) -> BaseModel:
        """解析 JSON 文本并通过响应模型校验。"""
        parsed_json = OpenAICompatibleLlmService._extract_json_payload(content)
        try:
            return response_model.model_validate(parsed_json)
        except ValidationError as exc:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回结果结构不符合预期",
                {"errors": exc.errors(), "payload": parsed_json},
            ) from exc

    @staticmethod
    def _extract_response_content(payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        text_parts: list[str] = []
        for output_item in payload.get("output") or []:
            if not isinstance(output_item, dict):
                continue
            content = output_item.get("content")
            if isinstance(content, str) and content.strip():
                text_parts.append(content.strip())
                continue
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if not isinstance(text, str):
                    text = content_item.get("output_text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())

        content = "\n".join(text_parts).strip()
        if not content:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回结果缺少文本内容")
        return content

    @staticmethod
    def _extract_chat_completion_content(payload: dict[str, Any]) -> str:
        """从 Chat Completions 响应中提取文本内容。"""
        choices = payload.get("choices") or []
        if not choices:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回结果缺少 choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text") or ""))
            content = "\n".join(item for item in text_parts if item)
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
            prompt_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
            completion_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
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
