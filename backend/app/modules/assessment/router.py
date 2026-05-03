"""
@Date: 2026-04-29
@Author: xisy
@Discription: 测评模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import (
    AssessmentBlueprintDetailResponse,
    AssessmentBlueprintListItemResponse,
    AssessmentTaskCreateRequest,
    PaperResultDetailResponse,
    PaperResultListItemResponse,
)
from app.modules.assessment.service import AssessmentService
from app.modules.auth.models import SysUser
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["测评"])


def get_assessment_service(session: Annotated[Session, Depends(get_db_session)]) -> AssessmentService:
    """构造测评服务依赖。"""
    return AssessmentService(session, AssessmentRepository(session))


@router.post(
    "/curriculum-plans/{curriculum_plan_id}/assessment-tasks",
    summary="创建按需测评生成任务",
    description="为当前教师可见的课程大纲创建测评生成任务，生成测评蓝图、试卷和题目。",
    operation_id="assessment_task_create",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_assessment_task(
    request: AssessmentTaskCreateRequest,
    curriculum_plan_id: int = Path(..., description="课程大纲主键", examples=[1]),
    service: Annotated[AssessmentService, Depends(get_assessment_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建按需测评生成任务。"""
    task = service.create_assessment_task(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
        request=request,
    )
    return ResponseFactory.success(task.model_dump(mode="json"), "创建测评生成任务成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/assessment-blueprints",
    summary="获取测评蓝图列表",
    description="分页获取指定课程大纲下的测评蓝图版本列表，可按测评场景筛选。",
    operation_id="assessment_blueprint_list",
    response_model=ApiResponse[PaginatedData[AssessmentBlueprintListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_assessment_blueprints(
    curriculum_plan_id: int = Query(..., description="课程大纲主键", examples=[1]),
    scenario_type: str | None = Query(default=None, description="测评场景类型", examples=["unit_test"]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[AssessmentService, Depends(get_assessment_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取测评蓝图列表。"""
    items, total_count = service.list_assessment_blueprints(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
        scenario_type=scenario_type,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取测评蓝图列表成功",
    )


@router.get(
    "/assessment-blueprints/{assessment_blueprint_id}",
    summary="获取测评蓝图详情",
    description="获取单个测评蓝图版本的结构化内容。",
    operation_id="assessment_blueprint_detail",
    response_model=ApiResponse[AssessmentBlueprintDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_assessment_blueprint_detail(
    assessment_blueprint_id: int = Path(..., description="测评蓝图主键", examples=[1]),
    service: Annotated[AssessmentService, Depends(get_assessment_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取测评蓝图详情。"""
    detail = service.get_assessment_blueprint_detail(
        owner_user_id=current_user.id,
        assessment_blueprint_id=assessment_blueprint_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取测评蓝图详情成功")


@router.get(
    "/paper-results",
    summary="获取试卷结果列表",
    description="分页获取指定生成批次下的作业或试卷结果列表，可按场景类型筛选。",
    operation_id="paper_result_list",
    response_model=ApiResponse[PaginatedData[PaperResultListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_paper_results(
    generation_batch_id: int = Query(..., description="生成批次主键", examples=[1]),
    scene_type: str | None = Query(default=None, description="试卷场景类型", examples=["unit_test"]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[AssessmentService, Depends(get_assessment_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取试卷结果列表。"""
    items, total_count = service.list_paper_results(
        owner_user_id=current_user.id,
        generation_batch_id=generation_batch_id,
        scene_type=scene_type,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取试卷结果列表成功",
    )


@router.get(
    "/paper-results/{paper_result_id}",
    summary="获取试卷结果详情",
    description="获取单个作业或试卷结果的结构化内容与题目明细。",
    operation_id="paper_result_detail",
    response_model=ApiResponse[PaperResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_paper_result_detail(
    paper_result_id: int = Path(..., description="试卷结果主键", examples=[1]),
    service: Annotated[AssessmentService, Depends(get_assessment_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取试卷结果详情。"""
    detail = service.get_paper_result_detail(owner_user_id=current_user.id, paper_result_id=paper_result_id)
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取试卷结果详情成功")
