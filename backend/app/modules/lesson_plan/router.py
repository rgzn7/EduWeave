"""
@Date: 2026-04-26
@Author: xisy
@Discription: 教案模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanDetailResponse, LessonPlanListItemResponse
from app.modules.lesson_plan.service import LessonPlanService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["教案"])


def get_lesson_plan_service(session: Annotated[Session, Depends(get_db_session)]) -> LessonPlanService:
    """构造教案服务依赖。"""
    return LessonPlanService(session, LessonPlanRepository(session))


@router.get(
    "/lesson-plans",
    summary="获取教案列表",
    description="分页获取指定课程大纲下的教案版本列表。",
    operation_id="lesson_plan_list",
    response_model=ApiResponse[PaginatedData[LessonPlanListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_lesson_plans(
    curriculum_plan_id: int = Query(..., description="课程大纲主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[LessonPlanService, Depends(get_lesson_plan_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取教案列表。"""
    items, total_count = service.list_lesson_plans(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取教案列表成功",
    )


@router.get(
    "/lesson-plans/{lesson_plan_id}",
    summary="获取教案详情",
    description="获取单个教案版本的结构化内容。",
    operation_id="lesson_plan_detail",
    response_model=ApiResponse[LessonPlanDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_lesson_plan_detail(
    lesson_plan_id: int = Path(..., description="教案主键", examples=[1]),
    service: Annotated[LessonPlanService, Depends(get_lesson_plan_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取教案详情。"""
    detail = service.get_lesson_plan_detail(owner_user_id=current_user.id, lesson_plan_id=lesson_plan_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取教案详情成功")

