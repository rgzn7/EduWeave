"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.assessment.presets import QuestionType
from app.modules.auth.models import SysUser
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.homework.repository import HomeworkRepository
from app.modules.homework.schemas import (
    HomeworkBlueprintResponse,
    HomeworkQuestionListItemResponse,
    HomeworkResultDetailResponse,
    HomeworkResultListItemResponse,
)
from app.modules.homework.service import HomeworkService
from app.modules.task_center.schemas import TaskListItemResponse
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["课后作业"])


def get_homework_service(session: Annotated[Session, Depends(get_db_session)]) -> HomeworkService:
    """构造课后作业服务依赖。"""
    return HomeworkService(session, HomeworkRepository(session))


@router.post(
    "/lesson-plans/{lesson_plan_id}/homework-tasks",
    summary="创建课后作业生成任务",
    description="为当前教师可见的教案创建课后作业生成任务，按教案知识点与教学内容生成 6 题练习；同一教案不可重复生成。",
    operation_id="homework_task_create",
    response_model=ApiResponse[TaskListItemResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_homework_task(
    lesson_plan_id: int = Path(..., description="教案主键", examples=[1]),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """创建课后作业生成任务。"""
    task = service.create_homework_task(owner_user_id=current_user.id, lesson_plan_id=lesson_plan_id)
    return ResponseFactory.success(task.model_dump(mode="json"), "创建课后作业生成任务成功", status_code=status.HTTP_201_CREATED)


@router.get(
    "/lesson-plans/{lesson_plan_id}/homework-result",
    summary="按教案获取课后作业详情",
    description="按教案主键查询其唯一的课后作业结构化内容与题目明细，未生成时返回 404。",
    operation_id="homework_result_detail_by_lesson",
    response_model=ApiResponse[HomeworkResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_homework_result_by_lesson(
    lesson_plan_id: int = Path(..., description="教案主键", examples=[1]),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """按教案获取课后作业详情。"""
    detail = service.get_homework_result_detail_by_lesson(
        owner_user_id=current_user.id,
        lesson_plan_id=lesson_plan_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取课后作业详情成功")


@router.get(
    "/homework-results",
    summary="获取课后作业列表",
    description="按课程大纲或生成批次分页获取当前教师可见的课后作业，按课次序号升序排列。",
    operation_id="homework_result_list",
    response_model=ApiResponse[PaginatedData[HomeworkResultListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_homework_results(
    curriculum_plan_id: int | None = Query(default=None, ge=1, description="课程大纲主键", examples=[1]),
    generation_batch_id: int | None = Query(default=None, ge=1, description="生成批次主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课后作业列表。"""
    items, total_count = service.list_homework_results(
        owner_user_id=current_user.id,
        curriculum_plan_id=curriculum_plan_id,
        generation_batch_id=generation_batch_id,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取课后作业列表成功",
    )


@router.get(
    "/homework-results/{homework_result_id}",
    summary="获取课后作业详情",
    description="按主键查询单份课后作业的结构化内容与题目明细。",
    operation_id="homework_result_detail",
    response_model=ApiResponse[HomeworkResultDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_homework_result_detail(
    homework_result_id: int = Path(..., description="课后作业主键", examples=[1]),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课后作业详情。"""
    detail = service.get_homework_result_detail(
        owner_user_id=current_user.id,
        homework_result_id=homework_result_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取课后作业详情成功")


@router.post(
    "/homework-results/{homework_result_id}/export-docx",
    summary="导出课后作业 DOCX",
    description=(
        "将当前教师可见的课后作业结构化内容和题目明细同步导出为 DOCX 文件，并返回签名下载地址。\n\n"
        "DOCX 模板 v2（2026-05-27 起生效）共用以下约定：\n"
        "- 文件名面向教师可读：`{lesson_title}-第{N}讲-课后作业.docx`，无课次序号时省略 `-第{N}讲`；\n"
        "- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；\n"
        "- 渲染层不再展示英文枚举、内部追溯字段，题型/难度统一中文，选项以 `A. 内容` 形式呈现。"
    ),
    operation_id="homework_result_export_docx",
    response_model=ApiResponse[FileDownloadUrlResponse],
    status_code=status.HTTP_200_OK,
)
def export_homework_result_docx(
    homework_result_id: int = Path(..., description="课后作业主键", examples=[1]),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """导出课后作业 DOCX。"""
    result = service.export_homework_result_docx(
        owner_user_id=current_user.id,
        homework_result_id=homework_result_id,
    )
    return ResponseFactory.success(result.model_dump(mode="json"), "导出课后作业 DOCX 成功")


@router.get(
    "/homework-blueprints/{homework_blueprint_id}",
    summary="获取课后作业蓝图详情",
    description="按主键查询单份课后作业蓝图，包含策略与考查权重。",
    operation_id="homework_blueprint_detail",
    response_model=ApiResponse[HomeworkBlueprintResponse],
    status_code=status.HTTP_200_OK,
)
def get_homework_blueprint_detail(
    homework_blueprint_id: int = Path(..., description="课后作业蓝图主键", examples=[1]),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课后作业蓝图详情。"""
    detail = service.get_homework_blueprint_detail(
        owner_user_id=current_user.id,
        homework_blueprint_id=homework_blueprint_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取课后作业蓝图详情成功")


@router.get(
    "/homework-questions",
    summary="获取课后作业题目列表",
    description="按教案、作业、知识点、题型、难度筛选当前教师可见的作业题目，支持分页。",
    operation_id="homework_question_list",
    response_model=ApiResponse[PaginatedData[HomeworkQuestionListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_homework_questions(
    lesson_plan_id: int | None = Query(default=None, ge=1, description="教案主键", examples=[1]),
    homework_result_id: int | None = Query(default=None, ge=1, description="课后作业主键", examples=[1]),
    knowledge_point_id: int | None = Query(default=None, ge=1, description="知识点主键", examples=[1]),
    question_type: QuestionType | None = Query(
        default=None,
        description="题型：single_choice=单选题，fill_blank=填空题，short_answer=简答题",
        examples=["single_choice"],
    ),
    difficulty_level: int | None = Query(default=None, ge=1, le=5, description="难度等级（1-5）", examples=[2]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[HomeworkService, Depends(get_homework_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取课后作业题目列表。"""
    items, total_count = service.list_homework_questions(
        owner_user_id=current_user.id,
        lesson_plan_id=lesson_plan_id,
        homework_result_id=homework_result_id,
        knowledge_point_id=knowledge_point_id,
        question_type=question_type.value if question_type else None,
        difficulty_level=difficulty_level,
        page=page,
        page_size=page_size,
    )
    return ResponseFactory.paginated(
        items=[item.model_dump(mode="json") for item in items],
        total_count=total_count,
        page=page,
        page_size=page_size,
        message="获取课后作业题目列表成功",
    )
