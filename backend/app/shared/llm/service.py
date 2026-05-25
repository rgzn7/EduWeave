"""
@Date: 2026-05-16
@Author: xisy
@Discription: OpenAI 兼容 LLM 业务封装（含缺文本重试与 JSON 解析-修复循环）
"""

import json
import re
import time
from typing import Any, Callable

import structlog
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.llm.client import OpenAICompatibleEmbeddingClient, OpenAICompatibleLlmClient
from app.shared.llm.prompt_cache import apply_prompt_cache_identity, apply_prompt_cache_markers
from app.shared.llm.schemas import ChatMessage, EmbeddingUsage, LlmUsage

logger = structlog.get_logger(__name__)

LLM_REPAIR_PROMPT_CONTEXT_MAX_CHARS = 12000
LLM_REPAIR_SCHEMA_MAX_CHARS = 20000
LLM_REPAIR_ERROR_MAX_CHARS = 8000
LLM_REPAIR_RAW_OUTPUT_MAX_CHARS = 20000

_LLM_JSON_REPAIR_SYSTEM_PROMPT = "你是严谨的结构化输出修复助手，只输出合法 JSON 对象。Return valid json only."


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
        cache_biz_key: str | None = None,
        stable_prefix_message_count: int = 0,
        cache_user_id: int | None = None,
        on_usage: Callable[[LlmUsage], None] | None = None,
    ) -> BaseModel:
        """生成结构化 JSON 输出并解析为指定模型。

        三层健壮性：传输层瞬时错误重试（client）、缺文本重试（重发原始调用）、
        解析/校验失败时回调 LLM 自修复 JSON。

        提示词缓存可选参数：
        - cache_biz_key：派生 prompt_cache_key，按业务键分片复用上游前缀缓存。
        - stable_prefix_message_count：前缀消息数量，Anthropic 端在第 N 条挂 cache_control 标记。
        - cache_user_id：可选用户标识；仅在 settings.llm_prompt_cache_user_enabled 开启时注入 user 字段。
        - on_usage：每次成功调用 LLM 后回调一次（含缺文本重试与修复重试），供调用方聚合 cached_tokens。
        """
        raw_text, raw_payload = self._invoke_raw_text(
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            cache_biz_key=cache_biz_key,
            stable_prefix_message_count=stable_prefix_message_count,
            cache_user_id=cache_user_id,
        )
        if on_usage is not None and raw_payload is not None:
            on_usage(self.build_usage(raw_payload))
        return self._parse_or_repair(
            original_messages=messages,
            response_model=response_model,
            temperature=temperature,
            raw_text=raw_text,
            on_usage=on_usage,
        )

    def _invoke_raw_text(
        self,
        *,
        messages: list[ChatMessage],
        response_model: type[BaseModel],
        temperature: float,
        cache_biz_key: str | None = None,
        stable_prefix_message_count: int = 0,
        cache_user_id: int | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """按配置格式调用 LLM 并提取文本；返回成功但无文本时重发原始调用。

        返回 (text, raw_payload)：raw_payload 是上游成功响应的原始字典，调用方可经
        build_usage() 提取 LlmUsage（含 cached_tokens）。所有缺文本失败路径均抛异常。
        """
        api_format = self.settings.llm_api_format
        max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            if api_format == "chat":
                payload = self._build_chat_completion_payload(
                    messages=messages,
                    temperature=temperature,
                    cache_biz_key=cache_biz_key,
                    stable_prefix_message_count=stable_prefix_message_count,
                    cache_user_id=cache_user_id,
                )
                result = self.client.create_chat_completion(payload)
                text = self._extract_response_text(result)
                details_source = result
            else:
                payload = self._build_response_payload(
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    cache_biz_key=cache_biz_key,
                    stable_prefix_message_count=stable_prefix_message_count,
                    cache_user_id=cache_user_id,
                )
                streamed_text, final_payload = self.client.create_response_stream(payload)
                text = streamed_text or self._extract_response_text(final_payload)
                details_source = final_payload

            if text and text.strip():
                return text.strip(), details_source if isinstance(details_source, dict) else None

            details = self._build_missing_text_details(details_source, api_format)
            if attempt >= max_retries:
                raise AppException(
                    BusinessErrorCode.LLM_REQUEST_FAILED,
                    "LLM 返回结果缺少文本内容",
                    details,
                )
            logger.warning(
                "llm_missing_text_retrying",
                api_format=api_format,
                schema=response_model.__name__,
                attempt=attempt + 1,
                max_retries=max_retries,
                reason=details.get("reason"),
            )
            self._sleep_before_retry(attempt)
        raise AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "LLM 返回结果缺少文本内容")

    def _parse_or_repair(
        self,
        *,
        original_messages: list[ChatMessage],
        response_model: type[BaseModel],
        temperature: float,
        raw_text: str,
        on_usage: Callable[[LlmUsage], None] | None = None,
    ) -> BaseModel:
        """解析结构化输出；失败时回调 LLM 修复 JSON 后重试。

        修复路径不传入 cache 参数，避免修复请求与稳定前缀混入同一缓存分片；on_usage
        仍会对修复请求的使用量回调，便于调用方统计完整 token 成本。
        """
        current_text = raw_text
        last_error: AppException | None = None
        max_attempts = self.settings.llm_parse_repair_max_attempts
        for attempt in range(max_attempts + 1):
            try:
                return self._parse_structured(content=current_text, response_model=response_model)
            except AppException as exc:
                if exc.code != BusinessErrorCode.LLM_RESULT_INVALID:
                    raise
                last_error = exc
                if attempt >= max_attempts:
                    raise
                logger.warning(
                    "llm_structured_parse_failed_repairing",
                    schema=response_model.__name__,
                    repair_attempt=attempt + 1,
                    max_repair_attempts=max_attempts,
                    error_message=exc.message,
                )
                repair_messages = self._build_repair_messages(
                    original_messages=original_messages,
                    response_model=response_model,
                    invalid_text=current_text,
                    parse_error=exc,
                    repair_attempt=attempt + 1,
                )
                current_text, repair_payload = self._invoke_raw_text(
                    messages=repair_messages,
                    response_model=response_model,
                    temperature=temperature,
                )
                if on_usage is not None and repair_payload is not None:
                    on_usage(self.build_usage(repair_payload))
        if last_error is not None:
            raise last_error
        raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 生成结果结构不正确")

    @staticmethod
    def _translate_message(message: ChatMessage, api_format: str) -> dict[str, Any]:
        """把中性消息翻译为指定 API 格式的请求消息。

        content 为 str 时保持 model_dump 原样输出（零行为变化）；为中性 part
        列表时按 chat / responses 翻译为对应厂商结构。
        """
        if isinstance(message.content, str):
            return message.model_dump()
        translated_parts: list[dict[str, Any]] = []
        for part in message.content:
            part_type = part.get("type")
            if part_type == "text":
                text_value = str(part.get("text") or "")
                if api_format == "responses":
                    translated_parts.append({"type": "input_text", "text": text_value})
                else:
                    translated_parts.append({"type": "text", "text": text_value})
            elif part_type == "image":
                data_url = str(part.get("data_url") or "")
                if api_format == "responses":
                    translated_parts.append(
                        {"type": "input_image", "image_url": data_url, "detail": "auto"}
                    )
                else:
                    translated_parts.append(
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}}
                    )
        return {"role": message.role, "content": translated_parts}

    @staticmethod
    def _message_text(message: ChatMessage) -> str:
        """提取消息的纯文本内容（list 形态仅取 text part，丢弃图片）。"""
        if isinstance(message.content, str):
            return message.content
        return "\n".join(
            str(part.get("text") or "")
            for part in message.content
            if part.get("type") == "text"
        )

    def _build_response_payload(
        self,
        *,
        messages: list[ChatMessage],
        response_model: type[BaseModel],
        temperature: float,
        cache_biz_key: str | None = None,
        stable_prefix_message_count: int = 0,
        cache_user_id: int | None = None,
    ) -> dict[str, Any]:
        """构造 OpenAI Responses 结构化请求。"""
        # reasoning 类模型（如 gpt-5 系列）不接受 temperature，仅接受 reasoning.effort；
        # 若配置中显式给出 reasoning_effort，则忽略 temperature 以避免上游 400。
        translated = [self._translate_message(message, "responses") for message in messages]
        apply_prompt_cache_markers(
            translated,
            settings=self.settings,
            api_format="responses",
            stable_prefix_count=stable_prefix_message_count,
        )
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "input": translated,
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
        apply_prompt_cache_identity(
            payload,
            settings=self.settings,
            biz_key=cache_biz_key,
            user_id=cache_user_id,
        )
        return payload

    def _build_chat_completion_payload(
        self,
        *,
        messages: list[ChatMessage],
        temperature: float,
        cache_biz_key: str | None = None,
        stable_prefix_message_count: int = 0,
        cache_user_id: int | None = None,
    ) -> dict[str, Any]:
        """构造 Chat Completions 兼容结构化请求。"""
        # reasoning 类模型（如 gpt-5 系列）不接受 temperature，仅接受 reasoning_effort
        message_payloads = [self._translate_message(message, "chat") for message in messages]
        # 在追加 JSON 兜底提示之前先打 cache markers，确保锚点仍落在稳定前缀上。
        apply_prompt_cache_markers(
            message_payloads,
            settings=self.settings,
            api_format="chat",
            stable_prefix_count=stable_prefix_message_count,
        )
        # OpenAI 在使用 response_format=json_object 时要求 user 消息中出现 "json" 字样，
        # 否则会以 invalid_request_error 拒绝；此处兜底追加提示，避免上游 prompt 漏写。
        # 多模态 list 形态下 str(content) 不可靠，改为只扫描原始消息的 text 内容。
        if not any(
            message.role == "user" and "json" in self._message_text(message).lower()
            for message in messages
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
        apply_prompt_cache_identity(
            payload,
            settings=self.settings,
            biz_key=cache_biz_key,
            user_id=cache_user_id,
        )
        return payload

    def _build_repair_messages(
        self,
        *,
        original_messages: list[ChatMessage],
        response_model: type[BaseModel],
        invalid_text: str,
        parse_error: AppException,
        repair_attempt: int,
    ) -> list[ChatMessage]:
        """构造 JSON 修复消息：原始上下文 + 目标 Schema + 校验错误 + 上次坏输出。"""
        schema_text = self._dump_prompt_json(
            response_model.model_json_schema(), LLM_REPAIR_SCHEMA_MAX_CHARS
        )
        error_text = self._dump_prompt_json(
            {"message": parse_error.message, "details": parse_error.details},
            LLM_REPAIR_ERROR_MAX_CHARS,
        )
        original_context = "\n\n".join(
            f"[{message.role}]\n{self._message_text(message)}" for message in original_messages
        )
        context_text = self._clip_text(original_context, LLM_REPAIR_PROMPT_CONTEXT_MAX_CHARS)
        output_text = self._clip_text(invalid_text, LLM_REPAIR_RAW_OUTPUT_MAX_CHARS)
        repair_body = f"""你需要修复上一次 LLM 输出，使其严格符合 {response_model.__name__} 的 JSON Schema。这是第 {repair_attempt} 次修复尝试。

硬性要求：
1. 只输出一个合法 JSON 对象，不要 Markdown、代码块、解释文字或多余前后缀。
2. 只修复 JSON 结构、字段名、字段类型、字段数量、安全校验和缺失字段问题。
3. 不要新增原始任务未提供的事实或数据；信息不足时填写"原文未明确说明"。
4. 若原输出中有可用内容，优先保留并整理为合规结构；无法保留的字段按原任务要求补齐为合规内容。
5. 输出必须能直接被服务端 JSON 解析和 Schema 校验通过。

原始任务消息（可能已截断）：
{context_text}

目标 JSON Schema（可能已截断）：
{schema_text}

服务端校验错误：
{error_text}

上一次不合格输出（可能已截断）：
{output_text}""".strip()
        return [
            ChatMessage(role="system", content=_LLM_JSON_REPAIR_SYSTEM_PROMPT),
            ChatMessage(role="user", content=repair_body),
        ]

    def _sleep_before_retry(self, attempt: int) -> None:
        """按指数退避等待下一次重试。"""
        time.sleep(self.settings.llm_retry_base_seconds * (2**attempt))

    @staticmethod
    def _parse_structured(*, content: str, response_model: type[BaseModel]) -> BaseModel:
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
    def _extract_response_text(payload: dict[str, Any] | None) -> str | None:
        """兼容 Responses / Chat Completions 及部分代理返回格式提取文本。"""
        if not isinstance(payload, dict):
            return None

        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        texts: list[str] = []
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                direct_text = item.get("text")
                if isinstance(direct_text, str):
                    texts.append(direct_text)
                content_list = item.get("content")
                if not isinstance(content_list, list):
                    continue
                for content in content_list:
                    if not isinstance(content, dict):
                        continue
                    text = content.get("text")
                    if not isinstance(text, str):
                        text = content.get("output_text")
                    if not isinstance(text, str):
                        text = content.get("content")
                    if isinstance(text, str):
                        texts.append(text)
        if texts:
            joined = "\n".join(part for part in texts if part)
            if joined.strip():
                return joined

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    if message["content"].strip():
                        return message["content"]
                if isinstance(message, dict) and isinstance(message.get("content"), list):
                    for content in message["content"]:
                        if not isinstance(content, dict):
                            continue
                        text = content.get("text") or content.get("content")
                        if isinstance(text, str):
                            texts.append(text)
                if isinstance(choice.get("text"), str):
                    return choice["text"]
        if texts:
            joined = "\n".join(part for part in texts if part)
            if joined.strip():
                return joined
        return None

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """移除可能出现的代码块包裹，必要时回退到首尾花括号截取。"""
        stripped = text.strip()
        matched = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
        if matched:
            return matched.group(1).strip()
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start >= 0 and end > start:
                return stripped[start : end + 1]
            return stripped

    @staticmethod
    def _extract_json_payload(content: str) -> dict[str, Any]:
        normalized_content = OpenAICompatibleLlmService._strip_code_fence(content)
        try:
            parsed_payload = json.loads(normalized_content)
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
    def _build_missing_text_details(payload: dict[str, Any] | None, api_format: str) -> dict[str, Any]:
        """构造不包含原文内容的 LLM 空文本诊断信息。"""
        data = payload if isinstance(payload, dict) else {}
        output = data.get("output")
        choices = data.get("choices")
        usage = data.get("usage")
        return {
            "api_format": api_format,
            "reason": "missing_text",
            "response_keys": sorted(str(key) for key in data.keys()),
            "status": data.get("status"),
            "error": data.get("error"),
            "incomplete_details": data.get("incomplete_details"),
            "output_count": len(output) if isinstance(output, list) else None,
            "choice_count": len(choices) if isinstance(choices, list) else None,
            "usage": usage if isinstance(usage, dict) else None,
        }

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        """将文本裁剪到指定字符数，空间足够时追加省略标记。"""
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return f"{text[: max_chars - 3].rstrip()}..."

    @staticmethod
    def _dump_prompt_json(value: Any, max_chars: int) -> str:
        """把诊断对象序列化为适合放进提示词的 JSON 文本。"""
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except TypeError:
            text = str(value)
        return OpenAICompatibleLlmService._clip_text(text, max_chars)

    @staticmethod
    def build_usage(payload: dict[str, Any]) -> LlmUsage:
        """从原始响应中提取使用量，含三协议缓存命中 token 兼容读取。

        缓存命中读取优先级：
        - OpenAI Responses: usage.input_tokens_details.cached_tokens
        - OpenAI Chat:      usage.prompt_tokens_details.cached_tokens
        - Anthropic 兼容:    usage.cache_read_input_tokens
        """
        usage = payload.get("usage") or {}
        cached_tokens = 0
        for key in ("input_tokens_details", "prompt_tokens_details"):
            details = usage.get(key)
            if isinstance(details, dict):
                value = details.get("cached_tokens")
                if isinstance(value, int):
                    cached_tokens = value
                    break
        if not cached_tokens:
            fallback = usage.get("cache_read_input_tokens")
            if isinstance(fallback, int):
                cached_tokens = fallback
        return LlmUsage(
            prompt_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
            completion_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            cached_tokens=int(cached_tokens or 0),
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
