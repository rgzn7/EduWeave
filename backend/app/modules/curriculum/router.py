"""
@Date: 2026-04-26
@Author: xisy
@Discription: 课程大纲模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.schemas import CurriculumPlanDetailResponse, CurriculumPlanListItemResponse
from app.modules.curriculum.service import CurriculumService
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["课程大纲"])


def get_curriculum_service(session: Annotated[Session, Depends(get_db_session)]) -> CurriculumService:
    """构造课程大纲服务依赖。"""
    return CurriculumService(session, CurriculumRepository(session))


@router.get(
    "/curriculum-plans",
    summary="获取课程大纲列表",
    description="分页获取指定项目下的课程大纲版本列表，可按知识版本筛选。",
    operation_id="curriculum_plan_list",
    response_model=ApiResponse[PaginatedData[CurriculumPlanListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_curriculum_plans(
    project_id: int = Query(..., description="项目主键", examples=[1]),
    knowledge_version_id: int | None = Query(default=None, description="知识版本主键"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[CurriculumService, Depends(get_curriculum_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课程大纲列表。"""
    items, total_count = service.list_curriculum_plans(
        owner_user_id=current_user.id,
        project_id=project_id,
        knowledge_version_id=knowledge_version_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取课程大纲列表成功",
    )


@router.get(
    "/curriculum-plans/{curriculum_plan_id}",
    summary="获取课程大纲详情",
    description="获取单个课程大纲版本的结构化内容。",
    operation_id="curriculum_plan_detail",
    response_model=ApiResponse[CurriculumPlanDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_curriculum_plan_detail(
    curriculum_plan_id: int = Path(..., description="课程大纲主键", examples=[1]),
    service: Annotated[CurriculumService, Depends(get_curriculum_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课程大纲详情。"""
    detail = service.get_curriculum_plan_detail(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取课程大纲详情成功")


@router.post(
    "/curriculum-plans/{curriculum_plan_id}/export-docx",
    summary="导出课程大纲 DOCX",
    description=(
        "将当前教师可见的课程大纲结构化内容同步导出为 DOCX 文件，并返回签名下载地址。\n\n"
        "DOCX 模板 v2（2026-05-27 起生效）共用以下约定：\n"
        "- 文件名面向教师可读：`{plan_title}-课程大纲.docx`；\n"
        "- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；\n"
        "- 渲染层不再展示英文枚举与数据库内部追溯字段（`single_choice / fill_blank / focus / audience / source_trace` 等）。"
    ),
    operation_id="curriculum_plan_export_docx",
    response_model=ApiResponse[FileDownloadUrlResponse],
    status_code=status.HTTP_200_OK,
)
def export_curriculum_plan_docx(
    curriculum_plan_id: int = Path(..., description="课程大纲主键", examples=[1]),
    service: Annotated[CurriculumService, Depends(get_curriculum_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """导出课程大纲 DOCX。"""
    result = service.export_curriculum_plan_docx(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
    )
    return ResponseFactory.success(result.model_dump(mode="json"), "导出课程大纲 DOCX 成功")
