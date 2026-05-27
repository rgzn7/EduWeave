"""
@Date: 2026-05-27
@Author: xisy
@Discription: 生成过程展示模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.generation_process.schemas import GenerationProcessResponse
from app.modules.generation_process.service import GenerationProcessService
from app.schemas.response import ApiResponse, ResponseFactory

router = APIRouter(tags=["生成过程"])


def get_generation_process_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> GenerationProcessService:
    """构造生成过程展示服务依赖。"""
    return GenerationProcessService(session)


@router.get(
    "/projects/{project_id}/generation-process",
    summary="获取项目生成过程",
    description=(
        "将项目当前的内部任务聚合成 6 个产品化展示步骤（MinerU 教材解析、学情理解、知识点梳理、"
        "课程规划、教案生成、覆盖检查），用于 Phase 2 页面展示。响应包含面向用户的文案、状态、"
        "当前阶段、公开进度指标与公开结果指标，不暴露内部任务 ID、队列名、worker 信息等实现细节。"
    ),
    operation_id="generation_process_detail",
    response_model=ApiResponse[GenerationProcessResponse],
    status_code=status.HTTP_200_OK,
)
def get_generation_process(
    project_id: Annotated[int, Path(description="项目主键", examples=[1])],
    service: Annotated[GenerationProcessService, Depends(get_generation_process_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
):
    """获取项目生成过程。"""
    detail = service.get_process(owner_user_id=current_user.id, project_id=project_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取生成过程成功")
