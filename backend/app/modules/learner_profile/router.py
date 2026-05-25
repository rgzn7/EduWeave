"""
@Date: 2026-04-13
@Author: xisy
@Discription: 学情模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.learner_profile.repository import LearnerProfileRepository
from app.modules.learner_profile.schemas import (
    LearnerProfileBatchUploadRequest,
    LearnerProfileBatchUploadResponse,
    LearnerProfileFileDetailResponse,
    LearnerProfileFileListItemResponse,
    LearnerProfileManualRevisionRequest,
    LearnerProfileUploadRequest,
    LearnerProfileVersionListItemResponse,
    LearnerProfileVersionResponse,
)
from app.modules.learner_profile.service import LearnerProfileService
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

LEARNER_PROFILE_BATCH_UPLOAD_MAX_FILES = 20

router = APIRouter(tags=["学情"])


def get_learner_profile_service(session: Annotated[Session, Depends(get_db_session)]) -> LearnerProfileService:
    """构造学情服务依赖。"""
    return LearnerProfileService(session, LearnerProfileRepository(session))


@router.post(
    "/projects/{project_id}/learner-profiles",
    summary="上传学情文件",
    description="向指定项目上传 docx 学情文件，并按配置创建真实学情抽取任务（本地 python-docx 同步解析）。",
    operation_id="learner_profile_create",
    response_model=ApiResponse[LearnerProfileFileDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_learner_profile(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    file: UploadFile = File(..., description="学情 docx 文件"),
    request: LearnerProfileUploadRequest = Depends(LearnerProfileUploadRequest.as_form),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """上传学情文件。"""
    content = await file.read()
    detail = service.upload_profile_file(
        owner_user_id=current_user.id,
        project_id=project_id,
        filename=file.filename or "learner_profile.docx",
        content=content,
        content_type=file.content_type,
        title=request.title,
        grade_code=request.grade_code,
        subject_scope=request.subject_scope,
        textbook_version_hint_id=request.textbook_version_hint_id,
        auto_extract=request.auto_extract,
        set_as_current=request.set_as_current,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "上传学情文件成功", status_code=status.HTTP_201_CREATED)


@router.post(
    "/projects/{project_id}/learner-profiles/batch",
    summary="批量上传学情文件",
    description=(
        "向指定项目一次性上传多份 docx 学情文件，单批最多 "
        f"{LEARNER_PROFILE_BATCH_UPLOAD_MAX_FILES} 份。"
        "每份文件独立创建学情抽取任务，单个失败不影响其它文件，"
        "失败原因会按 filename 汇总在响应 failed 列表中。"
    ),
    operation_id="learner_profile_create_batch",
    response_model=ApiResponse[LearnerProfileBatchUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_learner_profiles_batch(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    files: list[UploadFile] = File(..., description=f"学情 docx 文件列表（≤{LEARNER_PROFILE_BATCH_UPLOAD_MAX_FILES} 份）"),
    request: LearnerProfileBatchUploadRequest = Depends(LearnerProfileBatchUploadRequest.as_form),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """批量上传学情文件。"""
    if not files:
        raise AppException(BusinessErrorCode.INVALID_FILE_TYPE, "学情批量上传至少需要 1 份文件")
    if len(files) > LEARNER_PROFILE_BATCH_UPLOAD_MAX_FILES:
        raise AppException(
            BusinessErrorCode.INVALID_FILE_TYPE,
            f"学情批量上传单批最多 {LEARNER_PROFILE_BATCH_UPLOAD_MAX_FILES} 份文件",
            {"received_count": len(files)},
        )
    prepared_files: list[tuple[str, bytes, str | None]] = []
    for upload_file in files:
        file_bytes = await upload_file.read()
        prepared_files.append((upload_file.filename or "learner_profile.docx", file_bytes, upload_file.content_type))
    batch_response = service.upload_profile_files_batch(
        owner_user_id=current_user.id,
        project_id=project_id,
        files=prepared_files,
        grade_code=request.grade_code,
        subject_scope=request.subject_scope,
        textbook_version_hint_id=request.textbook_version_hint_id,
        auto_extract=request.auto_extract,
        set_as_current=request.set_as_current,
    )
    return ResponseFactory.success(
        batch_response.model_dump(mode="json"),
        "学情批量上传完成",
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "/projects/{project_id}/learner-profiles",
    summary="获取学情文件列表",
    description="分页获取指定项目下的学情文件及其最新抽取结果摘要。",
    operation_id="learner_profile_list",
    response_model=ApiResponse[PaginatedData[LearnerProfileFileListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_learner_profiles(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取学情文件列表。"""
    items, total_count = service.list_profile_files(
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
        message="获取学情文件列表成功",
    )


@router.get(
    "/projects/{project_id}/learner-profiles/{profile_file_id}",
    summary="获取学情文件详情",
    description="获取指定项目下学情文件详情及其最新学情版本内容。",
    operation_id="learner_profile_detail",
    response_model=ApiResponse[LearnerProfileFileDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_learner_profile_detail(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    profile_file_id: int = Path(..., description="学情文件主键", examples=[1]),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取学情文件详情。"""
    detail = service.get_profile_file_detail(
        owner_user_id=current_user.id,
        project_id=project_id,
        profile_file_id=profile_file_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取学情文件详情成功")


@router.get(
    "/projects/{project_id}/learner-profiles/{profile_file_id}/versions",
    summary="获取学情版本列表",
    description="分页获取指定学情文件下的学情版本列表。",
    operation_id="learner_profile_version_list",
    response_model=ApiResponse[PaginatedData[LearnerProfileVersionListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_learner_profile_versions(
    project_id: int = Path(..., description="项目主键", examples=[1]),
    profile_file_id: int = Path(..., description="学情文件主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取学情版本列表。"""
    items, total_count = service.list_profile_versions(
        owner_user_id=current_user.id,
        project_id=project_id,
        profile_file_id=profile_file_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取学情版本列表成功",
    )


@router.get(
    "/learner-profile-versions/{profile_version_id}",
    summary="获取学情版本详情",
    description="获取单个学情版本详情及其结构化画像记录。",
    operation_id="learner_profile_version_detail",
    response_model=ApiResponse[LearnerProfileVersionResponse],
    status_code=status.HTTP_200_OK,
)
def get_learner_profile_version_detail(
    profile_version_id: int = Path(..., description="学情版本主键", examples=[1]),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取学情版本详情。"""
    detail = service.get_profile_version_detail(owner_user_id=current_user.id, profile_version_id=profile_version_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取学情版本详情成功")


@router.post(
    "/learner-profile-versions/{profile_version_id}/manual-revisions",
    summary="保存学情人工修正版本",
    description="提交完整的学情画像记录并生成新的学情版本，可按需切换为项目当前学情版本。",
    operation_id="learner_profile_manual_revision_create",
    response_model=ApiResponse[LearnerProfileVersionResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_learner_profile_manual_revision(
    request: LearnerProfileManualRevisionRequest,
    profile_version_id: int = Path(..., description="学情版本主键", examples=[1]),
    service: Annotated[LearnerProfileService, Depends(get_learner_profile_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """保存学情人工修正版本。"""
    detail = service.create_manual_revision(
        owner_user_id=current_user.id,
        profile_version_id=profile_version_id,
        request=request,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "保存学情人工修正版本成功", status_code=status.HTTP_201_CREATED)
