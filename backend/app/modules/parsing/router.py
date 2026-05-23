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
    ParseManualRevisionRequest,
    ParsePageResponse,
    ParseReparseTaskCreateRequest,
    ParseTaskCreateRequest,
    ParseVersionDetailResponse,
    ParseVersionEvidenceSummaryResponse,
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
    description="为指定教材版本创建全量解析任务，并由 Worker 对接 MinerU 执行真实解析。",
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


@router.post(
    "/parse-versions/{parse_version_id}/reparse-tasks",
    summary="创建页级重解析任务",
    description="针对指定解析版本的页码范围创建重解析任务，并生成新的解析版本。",
    operation_id="parsing_create_reparse_task",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_reparse_task(
    request: ParseReparseTaskCreateRequest,
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建页级重解析任务。"""
    task = service.create_reparse_task(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        request=request,
    )
    return ResponseFactory.success(task.model_dump(mode="json"), "创建页级重解析任务成功", status_code=status.HTTP_201_CREATED)


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


@router.post(
    "/parse-versions/{parse_version_id}/confirm",
    summary="确认解析版本",
    description="将解析成功的版本显式标记为已确认，使其可作为后续知识抽取的合法输入基线。",
    operation_id="parsing_confirm_version",
    response_model=ApiResponse[ParseVersionDetailResponse],
    status_code=status.HTTP_200_OK,
)
def confirm_parse_version(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """确认解析版本。"""
    detail = service.confirm_parse_version(owner_user_id=current_user.id, parse_version_id=parse_version_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "确认解析版本成功")


@router.get(
    "/parse-versions/{parse_version_id}/evidence-summary",
    summary="获取解析证据摘要",
    description="聚合解析版本的页数、block 统计、类型分布、MinerU 参数与示例 block，证明教材 PDF 已被结构化拆解。",
    operation_id="parsing_evidence_summary",
    response_model=ApiResponse[ParseVersionEvidenceSummaryResponse],
    status_code=status.HTTP_200_OK,
)
def get_parse_version_evidence_summary(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    sample_size: int = Query(
        default=6,
        ge=3,
        le=10,
        description="示例证据 block 数量，限制在 3-10 之间",
        examples=[6],
    ),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取解析证据摘要。"""
    summary = service.get_parse_version_evidence_summary(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        sample_size=sample_size,
    )
    return ResponseFactory.success(summary.model_dump(mode="json"), "获取解析证据摘要成功")


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


@router.post(
    "/parse-versions/{parse_version_id}/manual-revisions",
    summary="保存解析人工修正版本",
    description="提交指定页的人工修正结果，后端生成新的解析版本并可按需切换为当前有效版本。",
    operation_id="parsing_create_manual_revision",
    response_model=ApiResponse[ParseVersionDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_manual_revision(
    request: ParseManualRevisionRequest,
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    service: Annotated[ParsingService, Depends(get_parsing_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """保存解析人工修正版本。"""
    detail = service.create_manual_revision(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        request=request,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "保存解析人工修正版本成功", status_code=status.HTTP_201_CREATED)
