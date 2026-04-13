"""
@Date: 2026-04-11
@Author: xisy
@Discription: 系统健康检查服务
"""

import time

from redis import Redis

from app.core.config import Settings, get_settings
from app.core.database import check_mysql_health
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.storage import ObsStorageClient
from app.shared.utils.datetime_util import DateTimeUtil
from app.shared.vector import MilvusVectorService


class SystemService:
    """提供应用健康检查与就绪检查。"""

    def __init__(
        self,
        settings: Settings | None = None,
        vector_service: MilvusVectorService | None = None,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_service = vector_service or MilvusVectorService()
        self.storage_client = storage_client or ObsStorageClient(self.settings)

    def get_health(self) -> dict[str, str]:
        """返回存活探针数据。"""
        return {
            "status": "ok",
            "app_name": self.settings.app_name,
            "version": self.settings.app_version,
            "timestamp": DateTimeUtil.to_isoformat(DateTimeUtil.now_utc()),
        }

    def check_redis_health(self) -> dict[str, str | float]:
        """执行 Redis 健康检查。"""
        started_at = time.perf_counter()
        try:
            client = Redis.from_url(self.settings.redis_url)
            client.ping()
            return {
                "status": "ok",
                "detail": "Redis 连接正常",
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "detail": f"Redis 连接失败：{exc}",
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }

    def get_ready(self) -> dict[str, object]:
        """返回就绪探针数据。"""
        mysql_status = check_mysql_health()
        redis_status = self.check_redis_health()
        milvus_status = self.vector_service.health_check()
        obs_status = {"status": "not_checked", "detail": "OBS 连通性检查未纳入就绪门禁"}

        checks = {
            "mysql": mysql_status,
            "redis": redis_status,
            "milvus": milvus_status,
            "obs": obs_status,
        }
        is_ready = all(checks[key]["status"] == "ok" for key in ("mysql", "redis", "milvus"))
        payload = {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        }
        if not is_ready:
            raise AppException(
                BusinessErrorCode.DEPENDENCY_NOT_READY,
                "系统未就绪",
                details=checks,
                data=payload,
            )
        return payload


def get_system_service() -> SystemService:
    """构造系统服务依赖。"""
    return SystemService()
