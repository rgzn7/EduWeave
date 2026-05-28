"""
@Date: 2026-05-28
@Author: xisy
@Discription: OpenAI 兼容接口底层客户端（含瞬时错误重试与 Chat/Responses 流式读取）
"""

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode

_SSE_ERROR_EVENT_TYPES = {"error", "response.failed", "response.incomplete"}
_NON_RETRYABLE_STREAM_ERROR_MARKERS = {
    "authentication_error",
    "billing_error",
    "context_length_exceeded",
    "insufficient_quota",
    "invalid_api_key",
    "invalid_request",
    "invalid_request_error",
    "invalid_schema",
    "permission_denied",
    "permission_error",
    "schema_validation_error",
}


def _should_retry_http_error(exc: httpx.HTTPError, attempt: int, max_retries: int) -> bool:
    """判断 LLM/Embedding HTTP 错误是否应该重试。"""
    if attempt >= max_retries:
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code < 600
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _should_retry_stream_app_error(exc: AppException, attempt: int, max_retries: int) -> bool:
    """判断 HTTP 200 后流式错误事件是否应该按单次请求重试。"""
    if attempt >= max_retries or exc.code != BusinessErrorCode.LLM_REQUEST_FAILED:
        return False
    details = exc.details if isinstance(exc.details, dict) else {}
    if details.get("transport") != "stream":
        return False
    if details.get("event_type") not in _SSE_ERROR_EVENT_TYPES:
        return False
    return details.get("retryable") is not False


def _sleep_before_retry(attempt: int, base_seconds: int) -> None:
    """按指数退避等待下一次重试。"""
    time.sleep(base_seconds * (2**attempt))


def _build_http_error_details(exc: httpx.HTTPError) -> dict[str, Any]:
    """构造不包含敏感信息的上游 HTTP 错误详情。"""
    if not isinstance(exc, httpx.HTTPStatusError):
        return {"error": str(exc)}
    response = exc.response
    body_text: str | None
    try:
        body_text = response.text
    except httpx.ResponseNotRead:
        body_text = None
    if body_text:
        try:
            payload: Any = json.loads(body_text)
        except ValueError:
            payload = body_text[:1000]
    else:
        payload = None
    return {"status_code": response.status_code, "payload": payload}


def _resolve_error_event_type(event_type: str | None, data: dict[str, Any]) -> str | None:
    """从标准事件、data.type 与最终 response.status 中归一化错误事件类型。"""
    if event_type in _SSE_ERROR_EVENT_TYPES:
        return event_type
    inferred_event_type = data.get("type")
    if isinstance(inferred_event_type, str) and inferred_event_type in _SSE_ERROR_EVENT_TYPES:
        return inferred_event_type
    response_data = data.get("response")
    if isinstance(response_data, dict):
        status = response_data.get("status")
        if status == "failed":
            return "response.failed"
        if status == "incomplete":
            return "response.incomplete"
    return event_type


def _build_safe_sse_error_details(
    *,
    api_format: str,
    event_type: str | None,
    data: dict[str, Any],
    max_chars: int,
) -> dict[str, Any]:
    """构造可落库展示的流式错误详情，只保留安全字段。"""
    response_data = data.get("response")
    response = response_data if isinstance(response_data, dict) else {}
    error_data = data.get("error")
    if error_data is None:
        error_data = response.get("error")
    incomplete_details = data.get("incomplete_details")
    if incomplete_details is None:
        incomplete_details = response.get("incomplete_details")

    safe_error = _build_safe_error_object(error_data, max_chars=max_chars)
    safe_incomplete_details = _build_safe_incomplete_details(incomplete_details, max_chars=max_chars)
    details: dict[str, Any] = {
        "api_format": api_format,
        "transport": "stream",
        "event_type": event_type,
        "retryable": _is_retryable_stream_error(
            event_type=event_type,
            error=safe_error,
            incomplete_details=safe_incomplete_details,
        ),
    }
    response_summary = {
        key: _truncate_string(response.get(key), max_chars=max_chars)
        for key in ("id", "status")
        if response.get(key) is not None
    }
    if response_summary:
        details["response"] = response_summary
    if safe_error is not None:
        details["error"] = safe_error
    if safe_incomplete_details is not None:
        details["incomplete_details"] = safe_incomplete_details
    return details


def _build_safe_error_object(error_data: Any, *, max_chars: int) -> dict[str, Any] | None:
    """白名单化上游 error 对象，避免泄露 prompt 或过长响应。"""
    if error_data is None:
        return None
    if not isinstance(error_data, dict):
        return {"message": _truncate_string(error_data, max_chars=max_chars)}
    safe: dict[str, Any] = {}
    for key in ("code", "message", "type", "param"):
        value = error_data.get(key)
        if value is not None:
            safe[key] = _truncate_string(value, max_chars=max_chars)
    return safe or None


def _build_safe_incomplete_details(incomplete_details: Any, *, max_chars: int) -> dict[str, Any] | None:
    """白名单化 response.incomplete_details。"""
    if incomplete_details is None:
        return None
    if not isinstance(incomplete_details, dict):
        return {"reason": _truncate_string(incomplete_details, max_chars=max_chars)}
    reason = incomplete_details.get("reason")
    if reason is None:
        return None
    return {"reason": _truncate_string(reason, max_chars=max_chars)}


def _is_retryable_stream_error(
    *,
    event_type: str | None,
    error: dict[str, Any] | None,
    incomplete_details: dict[str, Any] | None,
) -> bool:
    """根据安全字段判断流式错误是否值得单次请求层重试。"""
    if event_type not in _SSE_ERROR_EVENT_TYPES:
        return False
    marker_values: list[str] = []
    if isinstance(error, dict):
        marker_values.extend(str(error.get(key, "")) for key in ("code", "type", "message"))
    if isinstance(incomplete_details, dict):
        marker_values.append(str(incomplete_details.get("reason", "")))
    normalized_markers = " ".join(marker_values).lower()
    if any(marker in normalized_markers for marker in _NON_RETRYABLE_STREAM_ERROR_MARKERS):
        return False
    return True


def _truncate_string(value: Any, *, max_chars: int) -> str:
    """把安全 detail 中的值转成字符串并限制长度。"""
    text = str(value)
    return text if len(text) <= max_chars else text[:max_chars]


class OpenAICompatibleLlmClient:
    """OpenAI 兼容结构化生成客户端。"""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=float(self.settings.llm_timeout_seconds))

    def _build_headers(self, *, stream: bool = False) -> dict[str, str]:
        api_key = self.settings.llm_api_key
        if not api_key:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "LLM_API_KEY 未配置",
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }

    def _build_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.settings.llm_api_base_url}{normalized_path}"

    def _require_model(self) -> None:
        if not self.settings.llm_model:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "LLM_MODEL 未配置",
            )

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 OpenAI 兼容聊天补全接口，瞬时错误最多重试 llm_max_retries 次。

        固定以 stream 模式请求：部分网关/中继（如 PackyAPI）对 /chat/completions
        恒返回 SSE chunk；同时对仍返回非流式 JSON 的网关做双模回退，返回与非流式
        一致的响应体，保持上层 _extract_response_text 契约不变。
        """
        self._require_model()
        url = self._build_url("/chat/completions")
        headers = self._build_headers(stream=True)
        stream_payload = {**payload, "stream": True}
        max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            try:
                return self._read_chat_completion_stream(url, headers, stream_payload)
            except AppException as exc:
                if not _should_retry_stream_app_error(exc, attempt, max_retries):
                    raise
                _sleep_before_retry(attempt, self.settings.llm_retry_base_seconds)
            except httpx.HTTPError as exc:
                if not _should_retry_http_error(exc, attempt, max_retries):
                    raise AppException(
                        BusinessErrorCode.LLM_REQUEST_FAILED,
                        "LLM 接口调用失败",
                        _build_http_error_details(exc),
                    ) from exc
                _sleep_before_retry(attempt, self.settings.llm_retry_base_seconds)
        raise AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "LLM 接口调用失败")

    def create_response_stream(self, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        """以流式方式调用 OpenAI Responses 接口。

        返回 (拼接文本或 None, 最终响应体)。非流式 /responses 在推理模型/代理下易返回空 output
        或超时，固定使用 stream 模式并在传输层重试瞬时错误。
        """
        self._require_model()
        url = self._build_url("/responses")
        headers = self._build_headers(stream=True)
        stream_payload = {**payload, "stream": True}
        max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            try:
                return self._read_responses_stream(url, headers, stream_payload)
            except AppException as exc:
                if not _should_retry_stream_app_error(exc, attempt, max_retries):
                    raise
                _sleep_before_retry(attempt, self.settings.llm_retry_base_seconds)
            except httpx.HTTPError as exc:
                if not _should_retry_http_error(exc, attempt, max_retries):
                    raise AppException(
                        BusinessErrorCode.LLM_REQUEST_FAILED,
                        "LLM 接口调用失败",
                        _build_http_error_details(exc),
                    ) from exc
                _sleep_before_retry(attempt, self.settings.llm_retry_base_seconds)
        raise AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "LLM 接口调用失败")

    def _read_responses_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        """读取 Responses SSE 事件，拼接 output_text.delta 并合并 output_item。"""
        text_parts: list[str] = []
        done_text: str | None = None
        final_response: dict[str, Any] | None = None
        stream_output_items: list[dict[str, Any]] = []

        with self.http_client.stream("POST", url, headers=headers, json=payload) as response:
            if response.is_error:
                response.read()
            response.raise_for_status()
            for event_type, data_text in self._iter_sse_events(response):
                if data_text == "[DONE]":
                    break
                data = self._parse_sse_json_data(data_text, event_type, api_format="responses")
                resolved_event_type = event_type or self._get_sse_event_type(data)
                self._raise_for_sse_error(
                    resolved_event_type,
                    data,
                    max_chars=self.settings.llm_stream_error_detail_max_chars,
                )

                if resolved_event_type == "response.output_text.delta" and isinstance(data.get("delta"), str):
                    text_parts.append(data["delta"])
                elif resolved_event_type == "response.output_text.done" and isinstance(data.get("text"), str):
                    # completed 事件里通常携带 usage / cached_tokens，记录文本后继续读完整个响应。
                    done_text = data["text"]
                elif resolved_event_type == "response.output_item.done" and isinstance(data.get("item"), dict):
                    stream_output_items.append(data["item"])
                elif resolved_event_type == "response.completed" and isinstance(data.get("response"), dict):
                    final_response = data["response"]
                    break
                else:
                    # PackyAPI 等中继可能在 /responses 端点回 chat.completion.chunk 形态，
                    # 此处兜底拼接其增量文本，避免 Responses 解析拿不到文本。
                    chat_piece = self._extract_chat_chunk_text(data)
                    if chat_piece:
                        text_parts.append(chat_piece)

        merged_response = self._merge_stream_output(final_response, stream_output_items)
        text = "".join(text_parts) or done_text
        return (text or None), merged_response

    def _read_chat_completion_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """读取 Chat Completions SSE chunk，拼接 choices[].delta.content。

        网关返回非流式 JSON 时回退到普通解析；最终合成与非流式一致的响应体，
        使上层 _extract_response_text / _build_missing_text_details 无需改动。
        """
        content_parts: list[str] = []
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None

        with self.http_client.stream("POST", url, headers=headers, json=payload) as response:
            if response.is_error:
                response.read()
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type and "json" in content_type:
                response.read()
                return self._finalize_json(response)
            for event_type, data_text in self._iter_sse_events(response):
                if data_text == "[DONE]":
                    break
                data = self._parse_sse_json_data(data_text, event_type, api_format="chat")
                self._raise_for_chat_stream_error(
                    data,
                    max_chars=self.settings.llm_stream_error_detail_max_chars,
                )

                piece = self._extract_chat_chunk_text(data)
                if piece:
                    content_parts.append(piece)
                choices = data.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    choice_finish_reason = choices[0].get("finish_reason")
                    if isinstance(choice_finish_reason, str):
                        finish_reason = choice_finish_reason
                if isinstance(data.get("usage"), dict):
                    usage = data["usage"]

        synthesized: dict[str, Any] = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "".join(content_parts)},
                    "finish_reason": finish_reason,
                }
            ]
        }
        if usage is not None:
            synthesized["usage"] = usage
        return synthesized

    @staticmethod
    def _extract_chat_chunk_text(data: dict[str, Any]) -> str | None:
        """从 chat.completion.chunk 形态的 SSE data 中提取增量文本。"""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
        # 标准流式只有 delta；个别中继会在末帧塞 message，仅在缺 delta 时兜底，避免重复累积。
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        return None

    @staticmethod
    def _raise_for_chat_stream_error(data: dict[str, Any], *, max_chars: int) -> None:
        """把 Chat Completions 流式 200+error 体转换为业务异常。"""
        error_data = data.get("error")
        if error_data is None:
            return
        raise AppException(
            BusinessErrorCode.LLM_REQUEST_FAILED,
            "LLM 流式调用失败",
            _build_safe_sse_error_details(
                api_format="chat",
                event_type="error",
                data={"error": error_data},
                max_chars=max_chars,
            ),
        )

    @staticmethod
    def _merge_stream_output(
        final_response: dict[str, Any] | None,
        stream_output_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把流式 output_item 合并进最终响应，去重已有 id。"""
        if not stream_output_items:
            return final_response or {}
        if final_response is None:
            return {"output": stream_output_items}
        output = final_response.get("output")
        if not isinstance(output, list) or not output:
            return {**final_response, "output": stream_output_items}
        seen_output_ids = {
            item.get("id") for item in output if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        merged_output = list(output)
        for item in stream_output_items:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id in seen_output_ids:
                continue
            merged_output.append(item)
        return {**final_response, "output": merged_output}

    @staticmethod
    def _iter_sse_events(response: httpx.Response) -> Iterator[tuple[str | None, str]]:
        """按 SSE 块解析 event 与 data 行。"""
        event_type: str | None = None
        data_lines: list[str] = []
        for line in response.iter_lines():
            if line == "":
                if data_lines:
                    yield event_type, "\n".join(data_lines)
                event_type = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if not separator:
                continue
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)
        if data_lines:
            yield event_type, "\n".join(data_lines)

    @staticmethod
    def _parse_sse_json_data(
        data_text: str,
        event_type: str | None,
        api_format: str = "responses",
    ) -> dict[str, Any]:
        """解析 SSE data JSON。"""
        try:
            data = json.loads(data_text)
        except json.JSONDecodeError as exc:
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "LLM 流式返回格式不正确",
                {"api_format": api_format, "transport": "stream", "event_type": event_type},
            ) from exc
        if isinstance(data, dict):
            return data
        raise AppException(
            BusinessErrorCode.LLM_REQUEST_FAILED,
            "LLM 流式返回格式不正确",
            {
                "api_format": api_format,
                "transport": "stream",
                "event_type": event_type,
                "data_type": type(data).__name__,
            },
        )

    @staticmethod
    def _get_sse_event_type(data: dict[str, Any]) -> str | None:
        """从 SSE data 中推断事件类型。"""
        event_type = data.get("type")
        return event_type if isinstance(event_type, str) else None

    @staticmethod
    def _raise_for_sse_error(event_type: str | None, data: dict[str, Any], *, max_chars: int) -> None:
        """把 Responses 流式错误事件转换为业务异常。"""
        resolved_event_type = _resolve_error_event_type(event_type, data)
        if resolved_event_type not in _SSE_ERROR_EVENT_TYPES:
            return
        raise AppException(
            BusinessErrorCode.LLM_REQUEST_FAILED,
            "LLM 流式调用失败",
            _build_safe_sse_error_details(
                api_format="responses",
                event_type=resolved_event_type,
                data=data,
                max_chars=max_chars,
            ),
        )

    @staticmethod
    def _finalize_json(response: httpx.Response) -> dict[str, Any]:
        """解析成功响应体，并兼容部分网关 200 + error 字段的情况。"""
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "LLM 接口返回了非 JSON 响应",
                {"status_code": response.status_code, "body": response.text},
            ) from exc
        if payload.get("error"):
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "LLM 接口调用失败",
                {"payload": payload},
            )
        return payload


class OpenAICompatibleEmbeddingClient:
    """OpenAI 兼容 Embedding 客户端。"""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=float(self.settings.embedding_timeout_seconds))

    def _build_headers(self) -> dict[str, str]:
        api_key = self.settings.embedding_api_key
        if not api_key:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "EMBEDDING_API_KEY 未配置",
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.settings.embedding_api_base_url}{normalized_path}"

    def create_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 OpenAI 兼容 Embedding 接口，瞬时错误最多重试 llm_max_retries 次。"""
        if not self.settings.embedding_model:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "EMBEDDING_MODEL 未配置",
            )
        url = self._build_url("/embeddings")
        headers = self._build_headers()
        max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            try:
                response = self.http_client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return self._finalize_json(response)
            except httpx.HTTPError as exc:
                if not _should_retry_http_error(exc, attempt, max_retries):
                    raise AppException(
                        BusinessErrorCode.LLM_REQUEST_FAILED,
                        "Embedding 接口调用失败",
                        _build_http_error_details(exc),
                    ) from exc
                _sleep_before_retry(attempt, self.settings.llm_retry_base_seconds)
        raise AppException(BusinessErrorCode.LLM_REQUEST_FAILED, "Embedding 接口调用失败")

    @staticmethod
    def _finalize_json(response: httpx.Response) -> dict[str, Any]:
        """解析成功响应体，并兼容部分网关 200 + error 字段的情况。"""
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "Embedding 接口返回了非 JSON 响应",
                {"status_code": response.status_code, "body": response.text},
            ) from exc
        if payload.get("error"):
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "Embedding 接口调用失败",
                {"payload": payload},
            )
        return payload
