"""
@Date: 2026-04-14
@Author: xisy
@Discription: MinerU HTTP 客户端封装
"""

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.mineru.schemas import MineruBatchFileResult, MineruUploadBatchResult


class MineruClient:
    """封装 MinerU 官方批量解析接口。"""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=60.0)

    def _get_token(self) -> str:
        token = self.settings.mineru_api_token
        if not token:
            raise AppException(
                BusinessErrorCode.SYSTEM_CONFIG_INVALID,
                "MinerU API Token 未配置",
            )
        return token

    def _build_api_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        base_url = self.settings.mineru_api_base_url.rstrip("/")
        if base_url.endswith("/api/v4"):
            return f"{base_url}{normalized_path}"
        return f"{base_url}/api/v4{normalized_path}"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def _ensure_success(self, response: httpx.Response, error_code: BusinessErrorCode, default_message: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                error_code,
                default_message,
                {"status_code": response.status_code, "body": response.text},
            ) from exc

        if response.status_code >= 400:
            raise AppException(
                error_code,
                payload.get("msg") or default_message,
                {"status_code": response.status_code, "payload": payload},
            )
        if payload.get("code") != 0:
            raise AppException(
                error_code,
                payload.get("msg") or default_message,
                {"payload": payload},
            )
        return payload

    def request_upload_urls(
        self,
        *,
        files: list[dict[str, Any]],
        model_version: str,
        language: str | None = None,
        enable_formula: bool | None = None,
        enable_table: bool | None = None,
    ) -> MineruUploadBatchResult:
        """申请本地文件上传链接。"""
        payload = {
            "files": files,
            "model_version": model_version,
            "language": language or self.settings.mineru_default_language,
            "enable_formula": self.settings.mineru_enable_formula if enable_formula is None else enable_formula,
            "enable_table": self.settings.mineru_enable_table if enable_table is None else enable_table,
        }
        response = self.http_client.post(
            self._build_api_url("/file-urls/batch"),
            headers=self._build_headers(),
            json=payload,
        )
        result = self._ensure_success(response, BusinessErrorCode.MINERU_SUBMIT_FAILED, "申请 MinerU 上传链接失败")
        data = result.get("data") or {}
        batch_id = data.get("batch_id")
        raw_file_urls = data.get("file_urls") or data.get("files") or []
        file_urls: list[str] = []
        for item in raw_file_urls:
            if isinstance(item, str) and item:
                file_urls.append(item)
                continue
            if isinstance(item, dict):
                url = item.get("url") or item.get("upload_url") or item.get("put_url")
                if isinstance(url, str) and url:
                    file_urls.append(url)
        if not batch_id or not file_urls:
            raise AppException(
                BusinessErrorCode.MINERU_RESULT_INVALID,
                "MinerU 上传链接响应缺少必要字段",
                {"payload": result},
            )
        return MineruUploadBatchResult(batch_id=batch_id, file_urls=file_urls, trace_id=result.get("trace_id"))

    def upload_file(self, upload_url: str, content: bytes) -> None:
        """向 MinerU 提供的临时地址上传文件。"""
        response = self.http_client.put(upload_url, content=content, headers={"Accept": "*/*"})
        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.MINERU_SUBMIT_FAILED,
                "上传文件到 MinerU 失败",
                {"status_code": response.status_code, "body": response.text},
            )

    def get_batch_results(self, batch_id: str) -> list[MineruBatchFileResult]:
        """查询批量任务结果。"""
        response = self.http_client.get(
            self._build_api_url(f"/extract-results/batch/{batch_id}"),
            headers=self._build_headers(),
        )
        result = self._ensure_success(response, BusinessErrorCode.MINERU_TASK_FAILED, "查询 MinerU 任务结果失败")
        extract_results = (result.get("data") or {}).get("extract_result") or []
        normalized_results: list[MineruBatchFileResult] = []
        for item in extract_results:
            normalized_results.append(
                MineruBatchFileResult(
                    file_name=item.get("file_name") or "",
                    state=item.get("state") or "",
                    full_zip_url=item.get("full_zip_url"),
                    err_msg=item.get("err_msg"),
                    data_id=item.get("data_id"),
                    extract_progress=item.get("extract_progress"),
                )
            )
        return normalized_results

    def poll_batch_result(
        self,
        *,
        batch_id: str,
        data_id: str | None = None,
        file_name: str | None = None,
        on_progress: Callable[[MineruBatchFileResult], None] | None = None,
    ) -> MineruBatchFileResult:
        """轮询指定批量任务中的单文件结果。"""
        deadline = time.monotonic() + self.settings.mineru_poll_timeout_seconds
        pending_states = {"waiting-file", "pending", "running", "converting"}
        while time.monotonic() < deadline:
            results = self.get_batch_results(batch_id)
            target_result = self._pick_target_result(results, data_id=data_id, file_name=file_name)
            if target_result is None:
                time.sleep(self.settings.mineru_poll_interval_seconds)
                continue
            if target_result.state == "done" and target_result.full_zip_url:
                return target_result
            if target_result.state == "failed":
                raise AppException(
                    BusinessErrorCode.MINERU_TASK_FAILED,
                    "MinerU 解析任务失败",
                    {
                        "batch_id": batch_id,
                        "data_id": target_result.data_id,
                        "file_name": target_result.file_name,
                        "err_msg": target_result.err_msg,
                    },
                )
            if target_result.state not in pending_states:
                raise AppException(
                    BusinessErrorCode.MINERU_RESULT_INVALID,
                    "MinerU 返回了无法识别的任务状态",
                    {
                        "batch_id": batch_id,
                        "data_id": target_result.data_id,
                        "file_name": target_result.file_name,
                        "state": target_result.state,
                    },
                )
            if on_progress is not None:
                on_progress(target_result)
            time.sleep(self.settings.mineru_poll_interval_seconds)

        raise AppException(
            BusinessErrorCode.MINERU_POLL_TIMEOUT,
            "MinerU 解析结果轮询超时",
            {"batch_id": batch_id, "data_id": data_id, "file_name": file_name},
        )

    def download_full_zip(self, full_zip_url: str) -> bytes:
        """下载 MinerU 解析结果压缩包。"""
        response = self.http_client.get(full_zip_url)
        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.MINERU_RESULT_INVALID,
                "下载 MinerU 结果压缩包失败",
                {"status_code": response.status_code, "body": response.text},
            )
        return response.content

    @staticmethod
    def _pick_target_result(
        results: list[MineruBatchFileResult],
        *,
        data_id: str | None,
        file_name: str | None,
    ) -> MineruBatchFileResult | None:
        for item in results:
            if data_id and item.data_id == data_id:
                return item
        for item in results:
            if file_name and item.file_name == file_name:
                return item
        if len(results) == 1:
            return results[0]
        return None
