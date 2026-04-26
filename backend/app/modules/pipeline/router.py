"""
@Date: 2026-04-26
@Author: xisy
@Discription: 生成编排模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import (
    GenerationBatchCreateRequest,
    GenerationBatchDetailResponse,
    GenerationBatchListItemResponse,
)
from app.modules.pipeline.service import PipelineService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["生成编排"])


def get_pipeline_service(session: Annotated[Session, Depends(get_db_session)]) -> PipelineService:
    """构造生成编排服务依赖。"""
    return PipelineService(session, PipelineRepository(session))


@router.post(
    "/generation-batches",
    summary="创建生成批次",
    description="冻结知识版本与学情版本基线，创建生成批次并自动发起课程大纲生成任务。",
    operation_id="pipeline_generation_batch_create",
    response_model=ApiResponse[GenerationBatchDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_generation_batch(
    request: GenerationBatchCreateRequest,
    service: Annotated[PipelineService, Depends(get_pipeline_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建生成批次。"""
    detail = service.create_generation_batch(owner_user_id=current_user.id, request=request)
    return ResponseFactory.success(detail.model_dump(mode="json"), "创建生成批次成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/generation-batches",
    summary="获取生成批次列表",
    description="分页获取指定项目下的生成批次列表。",
    operation_id="pipeline_generation_batch_list",
    response_model=ApiResponse[PaginatedData[GenerationBatchListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_generation_batches(
    project_id: int = Query(..., description="项目主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[PipelineService, Depends(get_pipeline_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取生成批次列表。"""
    items, total_count = service.list_generation_batches(
        owner_user_id=current_user.id,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取生成批次列表成功",
    )


@router.get(
    "/generation-batches/{generation_batch_id}",
    summary="获取生成批次详情",
    description="获取生成批次的基线快照、状态和关联任务列表。",
    operation_id="pipeline_generation_batch_detail",
    response_model=ApiResponse[GenerationBatchDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_generation_batch_detail(
    generation_batch_id: int = Path(..., description="生成批次主键", examples=[1]),
    service: Annotated[PipelineService, Depends(get_pipeline_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取生成批次详情。"""
    detail = service.get_generation_batch_detail(
        owner_user_id=current_user.id,
        generation_batch_id=generation_batch_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取生成批次详情成功")
