"""
@Date: 2026-05-26
@Author: xisy
@Discription: 一键生成编排模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.orchestrator.schemas import GenerationRunCreateRequest, GenerationRunResponse
from app.modules.orchestrator.service import OrchestratorService
from app.schemas.response import ApiResponse, ResponseFactory

router = APIRouter(tags=["一键生成"])


def get_orchestrator_service(session: Annotated[Session, Depends(get_db_session)]) -> OrchestratorService:
    """构造一键生成编排服务依赖。"""
    return OrchestratorService(session)


@router.post(
    "/projects/{project_id}/generation-runs",
    summary="启动一键生成",
    description=(
        "为指定项目启动一次完整的 Phase2 生成运行（教材解析 → 学情分析 → 知识结构 → 课程规划 → 教案 → 覆盖检查）。"
        "后端持有完整编排权：前端只需点一次本接口，无需再单独触发 parse、knowledge、generation-batch。"
        "同一项目同时只允许一个活跃 run，重复调用本接口将返回当前活跃 run 详情（幂等）。"
        "auto_confirm_parse 默认开启；若关闭，解析成功后 run 将停在 waiting_user_confirm，等用户在解析页确认后自动续跑。"
    ),
    operation_id="orchestrator_start_generation_run",
    response_model=ApiResponse[GenerationRunResponse],
    status_code=status.HTTP_201_CREATED,
)
def start_generation_run(
    request: GenerationRunCreateRequest,
    project_id: int = Path(..., description="项目主键", examples=[1]),
    service: Annotated[OrchestratorService, Depends(get_orchestrator_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """启动一键生成。"""
    detail = service.start_generation_run(
        owner_user_id=current_user.id,
        project_id=project_id,
        request=request,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "启动一键生成成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/projects/{project_id}/generation-runs/active",
    summary="获取当前活跃一键生成运行",
    description="返回项目当前活跃（运行中或等待用户确认）的一键生成 run；无活跃 run 时返回 null。",
    operation_id="orchestrator_get_active_run",
    response_model=ApiResponse[GenerationRunResponse | None],
    status_code=status.HTTP_200_OK,
)
def get_active_generation_run(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    service: Annotated[OrchestratorService, Depends(get_orchestrator_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取当前活跃一键生成运行。"""
    detail = service.get_active_run(owner_user_id=current_user.id, project_id=project_id)
    payload = detail.model_dump(mode="json") if detail is not None else None
    return ResponseFactory.success(payload, "获取活跃一键生成成功")
