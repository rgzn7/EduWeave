"""
@Date: 2026-04-13
@Author: xisy
@Discription: 教材模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.textbook.repository import TextbookRepository
from app.modules.textbook.schemas import (
    TextbookUploadRequest,
    TextbookVersionDetailResponse,
    TextbookVersionListItemResponse,
)
from app.modules.textbook.service import TextbookService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["教材"])


def get_textbook_service(session: Annotated[Session, Depends(get_db_session)]) -> TextbookService:
    """构造教材服务依赖。"""
    return TextbookService(session, TextbookRepository(session))


@router.post(
    "/projects/{project_id}/textbooks",
    summary="上传教材文件",
    description="向指定项目上传 PDF 教材文件，并创建新的教材版本记录。",
    operation_id="textbook_create",
    response_model=ApiResponse[TextbookVersionDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_textbook(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    file: UploadFile = File(..., description="教材 PDF 文件"),
    request: TextbookUploadRequest = Depends(TextbookUploadRequest.as_form),
    service: Annotated[TextbookService, Depends(get_textbook_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """上传教材文件。"""
    content = await file.read()
    detail = service.upload_textbook(
        owner_user_id=current_user.id,
        project_id=project_id,
        filename=file.filename or "textbook.pdf",
        content=content,
        content_type=file.content_type,
        textbook_name=request.textbook_name,
        publisher=request.publisher,
        subject_code=request.subject_code,
        grade_code=request.grade_code,
        volume_code=request.volume_code,
        edition_label=request.edition_label,
        isbn=request.isbn,
        remark=request.remark,
        set_as_current=request.set_as_current,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "上传教材成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/projects/{project_id}/textbooks",
    summary="获取教材版本列表",
    description="分页获取指定项目下的教材版本列表。",
    operation_id="textbook_list",
    response_model=ApiResponse[PaginatedData[TextbookVersionListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_textbooks(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[TextbookService, Depends(get_textbook_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取教材版本列表。"""
    items, total_count = service.list_textbooks(
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
        message="获取教材版本列表成功",
    )


@router.get(
    "/projects/{project_id}/textbooks/{textbook_version_id}",
    summary="获取教材版本详情",
    description="获取指定项目下单个教材版本的详细信息。",
    operation_id="textbook_detail",
    response_model=ApiResponse[TextbookVersionDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_textbook_detail(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    textbook_version_id: int = Path(..., description="教材版本主键", examples=[1]),
    service: Annotated[TextbookService, Depends(get_textbook_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取教材版本详情。"""
    detail = service.get_textbook_detail(
        owner_user_id=current_user.id,
        project_id=project_id,
        textbook_version_id=textbook_version_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取教材版本详情成功")
