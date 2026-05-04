"""
@Date: 2026-05-04
@Author: xisy
@Discription: OpenAI 兼容接口底层客户端
"""

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode


class OpenAICompatibleLlmClient:
    """OpenAI 兼容结构化生成客户端。"""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=float(self.settings.llm_timeout_seconds))

    def _build_headers(self) -> dict[str, str]:
        api_key = self.settings.llm_api_key
        if not api_key:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "LLM_API_KEY 未配置",
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.settings.llm_api_base_url}{normalized_path}"

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 OpenAI 兼容聊天补全接口。"""
        if not self.settings.llm_model:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "LLM_MODEL 未配置",
            )
        response = self.http_client.post(
            self._build_url("/chat/completions"),
            headers=self._build_headers(),
            json=payload,
        )
        return self._ensure_success(response)

    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 OpenAI Responses 接口。"""
        if not self.settings.llm_model:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "LLM_MODEL 未配置",
            )
        response = self.http_client.post(
            self._build_url("/responses"),
            headers=self._build_headers(),
            json=payload,
        )
        return self._ensure_success(response)

    @staticmethod
    def _ensure_success(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "LLM 接口返回了非 JSON 响应",
                {"status_code": response.status_code, "body": response.text},
            ) from exc

        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "LLM 接口调用失败",
                {"status_code": response.status_code, "payload": payload},
            )
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
        """调用 OpenAI 兼容 Embedding 接口。"""
        if not self.settings.embedding_model:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "EMBEDDING_MODEL 未配置",
            )
        response = self.http_client.post(
            self._build_url("/embeddings"),
            headers=self._build_headers(),
            json=payload,
        )
        return self._ensure_success(response)

    @staticmethod
    def _ensure_success(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "Embedding 接口返回了非 JSON 响应",
                {"status_code": response.status_code, "body": response.text},
            ) from exc

        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "Embedding 接口调用失败",
                {"status_code": response.status_code, "payload": payload},
            )
        if payload.get("error"):
            raise AppException(
                BusinessErrorCode.LLM_REQUEST_FAILED,
                "Embedding 接口调用失败",
                {"payload": payload},
            )
        return payload
