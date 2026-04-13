"""
@Date: 2026-04-11
@Author: xisy
@Discription: 健康检查响应模型
"""

from pydantic import Field

from app.schemas.base import BaseSchema


class DependencyStatusResponse(BaseSchema):
    """依赖组件状态模型。"""

    status: str = Field(description="组件状态", examples=["ok"])
    detail: str = Field(description="状态说明", examples=["MySQL 连接正常"])
    latency_ms: float | None = Field(default=None, description="检查耗时（毫秒）", examples=[2.31])


class HealthResponse(BaseSchema):
    """存活探针响应模型。"""

    status: str = Field(description="应用状态", examples=["ok"])
    app_name: str = Field(description="应用名称", examples=["EduWeave Backend"])
    version: str = Field(description="应用版本", examples=["0.1.0"])
    timestamp: str = Field(description="当前时间", examples=["2026-04-11T10:00:00.000000Z"])


class ReadyResponse(BaseSchema):
    """就绪探针响应模型。"""

    status: str = Field(description="系统就绪状态", examples=["ready"])
    checks: dict[str, DependencyStatusResponse] = Field(description="依赖检查结果")
