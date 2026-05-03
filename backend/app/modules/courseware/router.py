"""
@Date: 2026-05-03
@Author: xisy
@Discription: 课件模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.courseware.repository import CoursewareRepository
from app.modules.courseware.schemas import (
    CoursewareReplyRequest,
    CoursewareResultDetailResponse,
    CoursewareResultListItemResponse,
)
from app.modules.courseware.service import CoursewareService
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["课件"])


def get_courseware_service(session: Annotated[Session, Depends(get_db_session)]) -> CoursewareService:
    """构造课件服务依赖。"""
    return CoursewareService(session, CoursewareRepository(session))


@router.post(
    "/lesson-plans/{lesson_plan_id}/courseware-tasks",
    summary="创建按需课件生成任务",
    description="为当前教师可见的教案创建 Raccoon PPT 课件生成任务并归档 PPTX。",
    operation_id="courseware_task_create",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_courseware_task(
    lesson_plan_id: int = Path(..., description="教案主键", examples=[1]),
    service: Annotated[CoursewareService, Depends(get_courseware_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建按需课件生成任务。"""
    task = service.create_courseware_task(owner_user_id=current_user.id, lesson_plan_id=lesson_plan_id)
    return ResponseFactory.success(task.model_dump(mode="json"), "创建课件生成任务成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/courseware-results",
    summary="获取课件结果列表",
    description="分页获取指定生成批次下的课件结果列表。",
    operation_id="courseware_result_list",
    response_model=ApiResponse[PaginatedData[CoursewareResultListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_courseware_results(
    generation_batch_id: int = Query(..., description="生成批次主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[CoursewareService, Depends(get_courseware_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课件结果列表。"""
    items, total_count = service.list_courseware_results(
        owner_user_id=current_user.id,
        generation_batch_id=generation_batch_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取课件结果列表成功",
    )


@router.get(
    "/courseware-results/{courseware_result_id}",
    summary="获取课件结果详情",
    description="获取单个课件结果的结构化内容、远程任务状态与导出文件引用。",
    operation_id="courseware_result_detail",
    response_model=ApiResponse[CoursewareResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_courseware_result_detail(
    courseware_result_id: int = Path(..., description="课件结果主键", examples=[1]),
    service: Annotated[CoursewareService, Depends(get_courseware_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课件结果详情。"""
    detail = service.get_courseware_result_detail(
        owner_user_id=current_user.id,
        courseware_result_id=courseware_result_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取课件结果详情成功")


@router.post(
    "/courseware-results/{courseware_result_id}/refresh",
    summary="刷新课件生成状态",
    description="继续查询 Raccoon PPT 远程任务，成功后归档 PPTX 并收口生成批次。",
    operation_id="courseware_result_refresh",
    response_model=ApiResponse[CoursewareResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def refresh_courseware_result(
    courseware_result_id: int = Path(..., description="课件结果主键", examples=[1]),
    service: Annotated[CoursewareService, Depends(get_courseware_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """刷新课件生成状态。"""
    detail = service.refresh_courseware_result(
        owner_user_id=current_user.id,
        courseware_result_id=courseware_result_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "刷新课件生成状态成功")


@router.post(
    "/courseware-results/{courseware_result_id}/reply",
    summary="回复课件生成补充问题",
    description="当 Raccoon PPT 任务需要补充信息时，提交回答并继续短轮询课件状态。",
    operation_id="courseware_result_reply",
    response_model=ApiResponse[CoursewareResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def reply_courseware_result(
    request: CoursewareReplyRequest,
    courseware_result_id: int = Path(..., description="课件结果主键", examples=[1]),
    service: Annotated[CoursewareService, Depends(get_courseware_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """回复课件生成补充问题。"""
    detail = service.reply_courseware_result(
        owner_user_id=current_user.id,
        courseware_result_id=courseware_result_id,
        answer=request.answer,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "回复课件生成补充问题成功")
