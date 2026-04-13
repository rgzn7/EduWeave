"""
@Date: 2026-04-11
@Author: xisy
@Discription: 系统健康检查路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.modules.system.schemas import HealthResponse, ReadyResponse
from app.modules.system.service import SystemService, get_system_service
from app.schemas.response import ApiResponse, ErrorDetail, ResponseFactory

router = APIRouter(tags=["系统"])


@router.get(
    "/health",
    summary="应用存活检查",
    description="返回应用进程存活状态，不校验外部依赖连通性。",
    operation_id="system_health",
    response_model=ApiResponse[HealthResponse],
)
def health(service: Annotated[SystemService, Depends(get_system_service)]):
    """应用存活检查接口。"""
    return ResponseFactory.success(service.get_health(), "应用运行正常")


@router.get(
    "/ready",
    summary="应用就绪检查",
    description="返回应用对 MySQL、Redis、Milvus 等核心依赖的就绪检查结果。",
    operation_id="system_ready",
    response_model=ApiResponse[ReadyResponse],
)
def ready(service: Annotated[SystemService, Depends(get_system_service)]):
    """应用依赖就绪检查接口。"""
    status_code, payload = service.get_ready()
    if status_code == 200:
        return ResponseFactory.success(payload, "系统已就绪", status_code=status_code)

    error = ErrorDetail(code="DEPENDENCY_NOT_READY", message="系统未就绪", details=payload["checks"])
    return JSONResponse(
        status_code=status_code,
        content=ResponseFactory.error(status_code, "系统未就绪", [error], data=payload),
    )
