"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    ChapterNodeResponse,
    KnowledgeManualRevisionRequest,
    KnowledgePointDetailResponse,
    KnowledgePointListItemResponse,
    KnowledgeTaskCreateRequest,
    KnowledgeVersionDetailResponse,
    KnowledgeVersionListItemResponse,
)
from app.modules.knowledge.service import KnowledgeService
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["知识结构化"])


def get_knowledge_service(session: Annotated[Session, Depends(get_db_session)]) -> KnowledgeService:
    """构造知识结构化服务依赖。"""
    return KnowledgeService(session, KnowledgeRepository(session))


@router.post(
    "/parse-versions/{parse_version_id}/knowledge-tasks",
    summary="创建知识抽取任务",
    description="为已确认的解析版本创建知识结构化任务，抽取章节树、知识点和证据映射。",
    operation_id="knowledge_create_task",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_task(
    request: KnowledgeTaskCreateRequest,
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建知识抽取任务。"""
    task = service.create_extract_task(
        owner_user_id=current_user.id,
        parse_version_id=parse_version_id,
        request=request,
    )
    return ResponseFactory.success(task.model_dump(mode="json"), "创建知识抽取任务成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/parse-versions/{parse_version_id}/knowledge-versions",
    summary="获取知识版本列表",
    description="分页获取指定解析版本下的知识结构版本列表。",
    operation_id="knowledge_version_list",
    response_model=ApiResponse[PaginatedData[KnowledgeVersionListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_knowledge_versions(
    parse_version_id: int = Path(..., description="解析版本主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取知识版本列表。"""
    items, total_count = service.list_knowledge_versions(
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
        message="获取知识版本列表成功",
    )


@router.get(
    "/knowledge-versions/{knowledge_version_id}",
    summary="获取知识版本详情",
    description="获取单个知识版本的基础信息和摘要统计。",
    operation_id="knowledge_version_detail",
    response_model=ApiResponse[KnowledgeVersionDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_knowledge_version_detail(
    knowledge_version_id: int = Path(..., description="知识版本主键", examples=[1]),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取知识版本详情。"""
    detail = service.get_knowledge_version_detail(
        owner_user_id=current_user.id,
        knowledge_version_id=knowledge_version_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取知识版本详情成功")


@router.get(
    "/knowledge-versions/{knowledge_version_id}/chapters",
    summary="获取知识章节树",
    description="获取知识版本下的平铺章节节点列表，前端可自行转换为树结构。",
    operation_id="knowledge_chapter_list",
    response_model=ApiResponse[list[ChapterNodeResponse]],
    status_code=status.HTTP_200_OK,
)
def list_chapters(
    knowledge_version_id: int = Path(..., description="知识版本主键", examples=[1]),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取知识章节树。"""
    chapters = service.list_chapters(
        owner_user_id=current_user.id,
        knowledge_version_id=knowledge_version_id,
    )
    return ResponseFactory.success([chapter.model_dump(mode="json") for chapter in chapters], "获取知识章节树成功")


@router.get(
    "/knowledge-versions/{knowledge_version_id}/points",
    summary="获取知识点列表",
    description="分页获取知识版本下的知识点列表，支持按章节和关键词筛选。",
    operation_id="knowledge_point_list",
    response_model=ApiResponse[PaginatedData[KnowledgePointListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_points(
    knowledge_version_id: int = Path(..., description="知识版本主键", examples=[1]),
    chapter_node_id: int | None = Query(default=None, description="章节节点主键"),
    keyword: str | None = Query(default=None, description="关键字"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取知识点列表。"""
    items, total_count = service.list_points(
        owner_user_id=current_user.id,
        knowledge_version_id=knowledge_version_id,
        chapter_node_id=chapter_node_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取知识点列表成功",
    )


@router.get(
    "/knowledge-points/{knowledge_point_id}",
    summary="获取知识点详情",
    description="获取单个知识点详情及其完整证据映射。",
    operation_id="knowledge_point_detail",
    response_model=ApiResponse[KnowledgePointDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_point_detail(
    knowledge_point_id: int = Path(..., description="知识点主键", examples=[1]),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取知识点详情。"""
    detail = service.get_point_detail(
        owner_user_id=current_user.id,
        knowledge_point_id=knowledge_point_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取知识点详情成功")


@router.post(
    "/knowledge-versions/{knowledge_version_id}/manual-revisions",
    summary="保存知识人工修正版本",
    description="按操作补丁提交知识修正内容，生成新的知识版本并替换当前可用版本。",
    operation_id="knowledge_manual_revision_create",
    response_model=ApiResponse[KnowledgeVersionDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_manual_revision(
    request: KnowledgeManualRevisionRequest,
    knowledge_version_id: int = Path(..., description="知识版本主键", examples=[1]),
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """保存知识人工修正版本。"""
    detail = service.create_manual_revision(
        owner_user_id=current_user.id,
        knowledge_version_id=knowledge_version_id,
        request=request,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "保存知识人工修正版本成功", status_code=status.HTTP_201_CREATED)
