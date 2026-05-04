"""
@Date: 2026-04-11
@Author: xisy
@Discription: 华为云 OBS 存储适配器
"""

from typing import Any

from obs import PutObjectHeader

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


class ObsStorageClient:
    """统一封装 OBS 客户端与对象路径能力。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    def get_client(self) -> Any:
        """懒加载创建 OBS 客户端。"""
        if self._client is not None:
            return self._client

        try:
            from obs import ObsClient
        except ImportError as exc:
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "未安装 obs SDK，无法初始化 OBS 客户端") from exc

        self._client = ObsClient(
            access_key_id=self.settings.obs_ak,
            secret_access_key=self.settings.obs_sk,
            server=self.settings.obs_endpoint,
        )
        return self._client

    def build_object_key(self, *segments: str, filename: str) -> str:
        """生成标准化对象路径。"""
        cleaned_segments = [segment.strip("/").strip() for segment in segments if segment and segment.strip("/").strip()]
        cleaned_filename = filename.lstrip("/").strip()
        return "/".join([self.settings.obs_base_prefix, *cleaned_segments, cleaned_filename])

    def upload_bytes(
        self,
        object_key: str,
        content: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """上传二进制内容到 OBS。"""
        headers = PutObjectHeader()
        if content_type:
            headers.contentType = content_type
        response = self.get_client().putContent(
            self.settings.obs_bucket,
            object_key,
            content=content,
            metadata=metadata,
            headers=headers,
        )
        if int(getattr(response, "status", 500)) >= 400:
            error_message = getattr(response, "errorMessage", "OBS 上传失败")
            logger.error("OBS 上传失败", object_key=object_key, error_message=error_message)
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, error_message)
        return {
            "bucket_name": self.settings.obs_bucket,
            "object_key": object_key,
            "etag": getattr(response, "etag", None),
            "request_id": getattr(response, "requestId", None),
        }

    def download_bytes(self, object_key: str) -> bytes:
        """读取对象二进制内容。"""
        response = self.get_client().getObject(
            self.settings.obs_bucket,
            object_key,
            loadStreamInMemory=True,
        )
        if int(getattr(response, "status", 500)) >= 400:
            error_message = getattr(response, "errorMessage", "OBS 下载失败")
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, error_message)
        return bytes(getattr(response.body, "buffer", b"") or b"")

    def delete_object(self, object_key: str) -> bool:
        """删除对象。"""
        response = self.get_client().deleteObject(self.settings.obs_bucket, object_key)
        return int(getattr(response, "status", 500)) < 400

    def create_download_signed_url(self, object_key: str, expires_in_seconds: int | None = None) -> str:
        """生成对象下载签名地址。"""
        expires = expires_in_seconds or self.settings.obs_signed_url_expire_seconds
        response = self.get_client().createSignedUrl(
            method="GET",
            bucketName=self.settings.obs_bucket,
            objectKey=object_key,
            expires=expires,
        )
        status = getattr(response, "status", 200)
        if int(status) >= 400:
            error_message = getattr(response, "errorMessage", "OBS 签名下载地址生成失败")
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, error_message)

        for attr_name in ("signedUrl", "signed_url", "url"):
            value = getattr(response, attr_name, None)
            if value:
                return value

        if isinstance(response, dict):
            for key in ("signedUrl", "signed_url", "url"):
                value = response.get(key)
                if value:
                    return value

        raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "OBS 签名下载地址生成失败")

    def head_object(self, object_key: str) -> dict[str, Any]:
        """查询对象元数据。"""
        response = self.get_client().headObject(self.settings.obs_bucket, object_key)
        if int(getattr(response, "status", 500)) >= 400:
            error_message = getattr(response, "errorMessage", "OBS 对象不存在")
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, error_message)
        return {
            "etag": getattr(response, "etag", None),
            "content_length": getattr(response, "contentLength", None),
            "last_modified": getattr(response, "lastModified", None),
        }

    def health_check(self) -> dict[str, str]:
        """执行 OBS 基础连通性检查。"""
        try:
            client = self.get_client()
            response = client.headBucket(self.settings.obs_bucket)
            if getattr(response, "status", None) and int(response.status) < 400:
                return {"status": "ok", "detail": "OBS 连接正常"}
            return {"status": "error", "detail": f"OBS 检查失败：{getattr(response, 'errorMessage', '未知错误')}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": f"OBS 检查异常：{exc}"}
