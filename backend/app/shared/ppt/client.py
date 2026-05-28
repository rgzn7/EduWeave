"""
@Date: 2026-05-03
@Author: xisy
@Discription: Raccoon PPT OpenAPI 客户端
"""

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.logging import get_logger
from app.shared.ppt.schemas import RaccoonPptJobState


logger = get_logger(__name__)


class RaccoonPptClient:
    """封装 Raccoon PPT 远程任务接口。"""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.Client(timeout=self._build_timeout(self.settings))

    @staticmethod
    def _build_timeout(settings: Settings) -> httpx.Timeout:
        """根据细分配置构造 httpx 超时；未配置细项时回退到统一超时。"""
        fallback = float(settings.raccoon_request_timeout_seconds)
        connect = float(getattr(settings, "raccoon_connect_timeout_seconds", None) or fallback)
        read = float(getattr(settings, "raccoon_read_timeout_seconds", None) or fallback)
        write = float(getattr(settings, "raccoon_write_timeout_seconds", None) or fallback)
        pool = float(getattr(settings, "raccoon_pool_timeout_seconds", None) or fallback)
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)

    def _get_token(self) -> str:
        """读取 Raccoon API Token。"""
        token = self.settings.raccoon_api_token
        if not token:
            raise AppException(BusinessErrorCode.SYSTEM_CONFIG_INVALID, "RACCOON_API_TOKEN 未配置")
        return token

    def _build_url(self, path: str) -> str:
        """拼接 Raccoon OpenAPI 地址。"""
        normalized_path = path if path.startswith("/") else f"/{path}"
        base_url = self.settings.raccoon_api_host.rstrip("/")
        if base_url.endswith("/api/open/office/v2"):
            return f"{base_url}{normalized_path}"
        return f"{base_url}/api/open/office/v2{normalized_path}"

    def _build_headers(self) -> dict[str, str]:
        """构造鉴权请求头。"""
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_ppt_job(self, *, prompt: str, role: str, scene: str, audience: str) -> RaccoonPptJobState:
        """创建远程 PPT 生成任务。"""
        payload = {"prompt": prompt, "role": role, "scene": scene, "audience": audience}
        url = self._build_url("/ppt_jobs")
        response = self._safe_request(
            "POST",
            url,
            failure_message="Raccoon PPT 创建任务超时，未获得远程 job_id，请稍后重试",
            headers=self._build_headers(),
            json=payload,
        )
        result = self._ensure_success(response, "创建 Raccoon PPT 任务失败")
        return self._normalize_job_state(result)

    def get_ppt_job(self, job_id: str) -> RaccoonPptJobState:
        """查询远程 PPT 任务状态。"""
        url = self._build_url(f"/ppt_jobs/{job_id}")
        response = self._safe_request(
            "GET",
            url,
            failure_message="Raccoon PPT 查询任务超时，请稍后重试",
            headers=self._build_headers(),
        )
        result = self._ensure_success(response, "查询 Raccoon PPT 任务失败")
        return self._normalize_job_state(result, fallback_job_id=job_id)

    def reply_ppt_job(self, *, job_id: str, answer: str) -> RaccoonPptJobState:
        """回复远程 PPT 任务的补充问题。"""
        url = self._build_url(f"/ppt_jobs/{job_id}/reply")
        response = self._safe_request(
            "POST",
            url,
            failure_message="Raccoon PPT 回复任务超时，请稍后重试",
            headers=self._build_headers(),
            json={"answer": answer},
        )
        result = self._ensure_success(response, "回复 Raccoon PPT 任务失败")
        return self._normalize_job_state(result, fallback_job_id=job_id)

    def download_pptx(self, download_url: str) -> bytes:
        """下载 Raccoon 生成的 PPTX 文件。"""
        response = self._safe_request(
            "GET",
            download_url,
            failure_message="Raccoon PPT 下载文件超时，请稍后重试",
        )
        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                "下载 Raccoon PPTX 文件失败",
                {"status_code": response.status_code, "body": response.text},
            )
        if not response.content:
            raise AppException(BusinessErrorCode.RACCOON_RESULT_INVALID, "Raccoon PPTX 下载内容为空")
        return response.content

    def _safe_request(
        self,
        method: str,
        url: str,
        *,
        failure_message: str,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        """统一发起 HTTP 请求，包装 httpx 超时与传输异常为 RACCOON_REQUEST_FAILED。"""
        try:
            if method == "POST":
                return self.http_client.post(url, headers=headers, json=json)
            if method == "GET":
                if headers is None:
                    return self.http_client.get(url)
                return self.http_client.get(url, headers=headers)
            raise ValueError(f"unsupported method: {method}")
        except httpx.TimeoutException as exc:
            logger.warning(
                "raccoon request timeout",
                method=method,
                url=url,
                exception_type=type(exc).__name__,
            )
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                failure_message,
                {"exception_type": type(exc).__name__, "url": url},
            ) from exc
        except httpx.TransportError as exc:
            logger.warning(
                "raccoon request transport error",
                method=method,
                url=url,
                exception_type=type(exc).__name__,
            )
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                "Raccoon PPT 请求传输失败，请稍后重试",
                {"exception_type": type(exc).__name__, "url": url},
            ) from exc

    @staticmethod
    def _ensure_success(response: httpx.Response, default_message: str) -> dict[str, Any]:
        """校验远程 API 响应。"""
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                default_message,
                {"status_code": response.status_code, "body": response.text},
            ) from exc

        if response.status_code >= 400:
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                payload.get("message") or payload.get("msg") or default_message,
                {"status_code": response.status_code, "payload": payload},
            )
        if payload.get("error"):
            raise AppException(BusinessErrorCode.RACCOON_REQUEST_FAILED, default_message, {"payload": payload})
        if "code" in payload and payload.get("code") not in (0, "0", 200, "200"):
            raise AppException(
                BusinessErrorCode.RACCOON_REQUEST_FAILED,
                payload.get("message") or payload.get("msg") or default_message,
                {"payload": payload},
            )
        return payload

    @classmethod
    def _normalize_job_state(cls, payload: dict[str, Any], fallback_job_id: str | None = None) -> RaccoonPptJobState:
        """兼容不同响应包裹格式并提取任务状态。"""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        job_id = data.get("job_id") or data.get("id") or data.get("jobId") or fallback_job_id
        status_value = data.get("status") or data.get("state") or data.get("job_status")
        if not job_id or not status_value:
            raise AppException(BusinessErrorCode.RACCOON_RESULT_INVALID, "Raccoon PPT 响应缺少任务ID或状态", {"payload": payload})

        required_input = data.get("required_user_input") or data.get("question") or data.get("user_input") or data.get("message")
        error_message = data.get("error_message") or data.get("err_msg") or data.get("error") or data.get("failure_reason")
        return RaccoonPptJobState(
            job_id=str(job_id),
            status=str(status_value),
            download_url=data.get("download_url") or data.get("downloadUrl") or data.get("file_url"),
            required_user_input=str(required_input) if required_input else None,
            error_message=str(error_message) if error_message else None,
            raw_payload=payload,
        )
