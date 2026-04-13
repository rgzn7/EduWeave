"""
@Date: 2026-04-13
@Author: xisy
@Discription: 任务中心模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskDetailResponse, TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["任务中心"])


def get_task_center_service(session: Annotated[Session, Depends(get_db_session)]) -> TaskCenterService:
    """构造任务中心服务依赖。"""
    return TaskCenterService(TaskCenterRepository(session))


@router.get(
    "/tasks",
    summary="获取任务列表",
    description="按项目、模块、任务类型和任务状态筛选当前教师可见的任务列表。",
    operation_id="task_center_list",
    response_model=ApiResponse[PaginatedData[TaskListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_tasks(
    service: Annotated[TaskCenterService, Depends(get_task_center_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    project_id: int | None = Query(default=None, description="项目主键"),
    module_code: str | None = Query(default=None, description="模块编码"),
    task_type: str | None = Query(default=None, description="任务类型"),
    task_status: str | None = Query(default=None, description="任务状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
):
    """获取任务列表。"""
    items, total_count = service.list_tasks(
        owner_user_id=current_user.id,
        project_id=project_id,
        module_code=module_code,
        task_type=task_type,
        task_status=task_status,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取任务列表成功",
    )


@router.get(
    "/tasks/{task_id}",
    summary="获取任务详情",
    description="获取当前教师可见的单个任务详情及其步骤信息。",
    operation_id="task_center_detail",
    response_model=ApiResponse[TaskDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_task_detail(
    task_id: int = Path(..., description="任务主键", examples=[1]),
    service: Annotated[TaskCenterService, Depends(get_task_center_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取任务详情。"""
    detail = service.get_task_detail(owner_user_id=current_user.id, task_id=task_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取任务详情成功")
