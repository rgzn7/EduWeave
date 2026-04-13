"""
@Date: 2026-04-13
@Author: xisy
@Discription: 项目模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.project.repository import ProjectRepository
from app.modules.project.schemas import (
    ProjectActiveRefsUpdateRequest,
    ProjectCreateRequest,
    ProjectDashboardResponse,
    ProjectDetailResponse,
    ProjectListItemResponse,
)
from app.modules.project.service import ProjectService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(prefix="/projects", tags=["项目"])


def get_project_service(session: Annotated[Session, Depends(get_db_session)]) -> ProjectService:
    """构造项目服务依赖。"""
    return ProjectService(session, ProjectRepository(session))


@router.post(
    "",
    summary="创建项目",
    description="创建新的教学项目，作为教材、学情、任务与结果的统一上下文容器。",
    operation_id="project_create",
    response_model=ApiResponse[ProjectDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequest,
    service: Annotated[ProjectService, Depends(get_project_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
):
    """创建项目。"""
    detail = service.create_project(current_user.id, request)
    return ResponseFactory.success(detail.model_dump(mode="json"), "创建项目成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "",
    summary="获取项目列表",
    description="分页获取当前教师创建的项目列表，支持按项目状态和学科筛选。",
    operation_id="project_list",
    response_model=ApiResponse[PaginatedData[ProjectListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_projects(
    service: Annotated[ProjectService, Depends(get_project_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    status_filter: str | None = Query(default=None, alias="status", description="项目状态"),
    subject_code: str | None = Query(default=None, description="学科编码"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
):
    """获取项目列表。"""
    items, total_count = service.list_projects(
        current_user.id,
        status=status_filter,
        subject_code=subject_code,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取项目列表成功",
    )


@router.get(
    "/{project_id}",
    summary="获取项目详情",
    description="获取当前教师拥有的项目详情及当前教材、学情引用信息。",
    operation_id="project_detail",
    response_model=ApiResponse[ProjectDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_project_detail(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    service: Annotated[ProjectService, Depends(get_project_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取项目详情。"""
    detail = service.get_project_detail(current_user.id, project_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取项目详情成功")


@router.get(
    "/{project_id}/dashboard",
    summary="获取项目工作台",
    description="获取项目工作台聚合数据，包括当前引用、输入链路统计和最近任务列表。",
    operation_id="project_dashboard",
    response_model=ApiResponse[ProjectDashboardResponse],
    status_code=status.HTTP_200_OK,
)
def get_project_dashboard(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    service: Annotated[ProjectService, Depends(get_project_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取项目工作台。"""
    detail = service.get_project_dashboard(current_user.id, project_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取项目工作台成功")


@router.patch(
    "/{project_id}/active-refs",
    summary="切换项目当前引用",
    description="切换项目当前默认教材版本和学情版本，版本必须属于当前项目。",
    operation_id="project_update_active_refs",
    response_model=ApiResponse[ProjectDetailResponse],
    status_code=status.HTTP_200_OK,
)
def update_project_active_refs(
    request: ProjectActiveRefsUpdateRequest,
    project_id: int = Path(..., description="项目主键", examples=[1]),
    service: Annotated[ProjectService, Depends(get_project_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """切换项目当前引用。"""
    detail = service.update_active_refs(
        current_user.id,
        project_id,
        current_textbook_version_id=request.current_textbook_version_id,
        current_learner_profile_version_id=request.current_learner_profile_version_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "切换项目当前引用成功")
