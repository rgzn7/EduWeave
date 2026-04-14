"""
@Date: 2026-04-14
@Author: xisy
@Discription: 文件访问模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.file_asset.repository import FileAssetRepository
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.file_asset.service import FileAssetService
from app.schemas.response import ApiResponse, ResponseFactory

router = APIRouter(tags=["文件"])


def get_file_asset_service(session: Annotated[Session, Depends(get_db_session)]) -> FileAssetService:
    """构造文件服务依赖。"""
    return FileAssetService(FileAssetRepository(session))


@router.get(
    "/files/{file_object_id}/download-url",
    summary="获取文件下载地址",
    description="为当前教师可见的文件对象生成临时签名下载地址。",
    operation_id="file_asset_download_url",
    response_model=ApiResponse[FileDownloadUrlResponse],
    status_code=status.HTTP_200_OK,
)
def get_file_download_url(
    file_object_id: int = Path(..., description="文件对象主键", examples=[1]),
    service: Annotated[FileAssetService, Depends(get_file_asset_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取文件下载地址。"""
    detail = service.get_download_url(owner_user_id=current_user.id, file_object_id=file_object_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取文件下载地址成功")
