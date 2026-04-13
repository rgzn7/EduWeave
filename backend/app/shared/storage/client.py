"""
@Date: 2026-04-11
@Author: xisy
@Discription: 华为云 OBS 存储适配器
"""

from typing import Any

from app.core.config import Settings, get_settings


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
            raise RuntimeError("未安装 obs SDK，无法初始化 OBS 客户端") from exc

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

