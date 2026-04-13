"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.parsing.repository import ParsingRepository
from app.modules.parsing.schemas import (
    ParseIssueResponse,
    ParsePageResponse,
    ParseTaskCreateRequest,
    ParseVersionDetailResponse,
    ParseVersionListItemResponse,
)
from app.modules.parsing.service import ParsingService
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["解析"])


def get_parsing_service(session: Annotated[Session, Depends(get_db_session)]) -> ParsingService:
    """构造解析服务依赖。"""
    return ParsingService(session, ParsingRepository(session))


@router.post(
    "/textbook-versions/{textbook_version_id}/parse-tasks",
    summary="创建教材解析任务",
    description="为指定教材版本创建全量解析任务，并按配置同步或异步执行占位解析。",
    operation_id="parsing_create_task",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_parse_task(
    request: ParseTaskCreateRequest,
    textbook_version_id: int = Path(..., description="教材版本主键", examples=[1]),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建教材解析任务。"""
    task = service.create_parse_task(
        owner_user_id=current_user.id,
        textbook_version_id=textbook_version_id,
        request=request,
    )
    return ResponseFactory.success(task.model_dump(mode="json"), "创建教材解析任务成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/textbook-versions/{textbook_version_id}/parse-versions",
    summary="获取解析版本列表",
    description="分页获取指定教材版本下的解析版本列表。",
    operation_id="parsing_version_list",
    response_model=ApiResponse[PaginatedData[ParseVersionListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_parse_versions(
    textbook_version_id: int = Path(..., description="教材版本主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取解析版本列表。"""
    items, total_count = service.list_parse_versions(
        owner_user_id=current_user.id,
        textbook_version_id=textbook_version_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取解析版本列表成功",
    )


@router.get(
    "/parse-versions/{parse_version_id}",
    summary="获取解析版本详情",
    description="获取单个解析版本的基础信息、状态和异常统计。",
    operation_id="parsing_version_detail",
    response_model=ApiResponse[ParseVersionDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_parse_version_detail(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取解析版本详情。"""
    detail = service.get_parse_version_detail(owner_user_id=current_user.id, parse_version_id=parse_version_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取解析版本详情成功")


@router.get(
    "/parse-versions/{parse_version_id}/pages",
    summary="获取解析页列表",
    description="分页获取解析页及其文本级块预览数据。",
    operation_id="parsing_page_list",
    response_model=ApiResponse[PaginatedData[ParsePageResponse]],
    status_code=status.HTTP_200_OK,
)
def list_parse_pages(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取解析页列表。"""
    items, total_count = service.list_parse_pages(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取解析页列表成功",
    )


@router.get(
    "/parse-versions/{parse_version_id}/issues",
    summary="获取解析异常列表",
    description="分页获取解析版本下的异常记录。",
    operation_id="parsing_issue_list",
    response_model=ApiResponse[PaginatedData[ParseIssueResponse]],
    status_code=status.HTTP_200_OK,
)
def list_parse_issues(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取解析异常列表。"""
    items, total_count = service.list_parse_issues(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取解析异常列表成功",
    )
