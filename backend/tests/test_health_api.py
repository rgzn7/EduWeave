"""
@Date: 2026-04-11
@Author: xisy
@Discription: 健康检查接口测试
"""

from app.main import app
from app.modules.system.service import get_system_service


class ReadySystemServiceStub:
    """已就绪系统服务桩。"""

    def get_health(self):
        return {
            "status": "ok",
            "app_name": "EduWeave Backend Test",
            "version": "0.1.0-test",
            "timestamp": "2026-04-11T00:00:00Z",
        }

    def get_ready(self):
        return (
            200,
            {
                "status": "ready",
                "checks": {
                    "mysql": {"status": "ok", "detail": "MySQL 连接正常", "latency_ms": 1.0},
                    "redis": {"status": "ok", "detail": "Redis 连接正常", "latency_ms": 1.0},
                    "milvus": {"status": "ok", "detail": "Milvus 连接正常"},
                    "obs": {"status": "not_checked", "detail": "OBS 连通性检查未纳入就绪门禁"},
                },
            },
        )


class NotReadySystemServiceStub(ReadySystemServiceStub):
    """未就绪系统服务桩。"""

    def get_ready(self):
        return (
            503,
            {
                "status": "not_ready",
                "checks": {
                    "mysql": {"status": "ok", "detail": "MySQL 连接正常", "latency_ms": 1.0},
                    "redis": {"status": "ok", "detail": "Redis 连接正常", "latency_ms": 1.0},
                    "milvus": {"status": "error", "detail": "Milvus 检查失败"},
                    "obs": {"status": "not_checked", "detail": "OBS 连通性检查未纳入就绪门禁"},
                },
            },
        )


def test_health_should_return_200(client) -> None:
    """健康检查应返回 200。"""
    app.dependency_overrides[get_system_service] = ReadySystemServiceStub
    response = client.get("/health")
    app.dependency_overrides.pop(get_system_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "ok"


def test_ready_should_return_200_when_dependencies_are_healthy(client) -> None:
    """当依赖都正常时 readiness 应返回 200。"""
    app.dependency_overrides[get_system_service] = ReadySystemServiceStub
    response = client.get("/ready")
    app.dependency_overrides.pop(get_system_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "ready"


def test_ready_should_return_503_when_milvus_is_unhealthy(client) -> None:
    """Milvus 异常时 readiness 应返回 503。"""
    app.dependency_overrides[get_system_service] = NotReadySystemServiceStub
    response = client.get("/ready")
    app.dependency_overrides.pop(get_system_service, None)

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"]["status"] == "not_ready"
    assert payload["errors"][0]["code"] == "DEPENDENCY_NOT_READY"

