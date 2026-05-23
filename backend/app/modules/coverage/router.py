"""
@Date: 2026-05-03
@Author: xisy
@Discription: 覆盖率分析模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.coverage.repository import CoverageRepository
from app.modules.coverage.schemas import CoverageReportDetailResponse, CoverageReportListItemResponse
from app.modules.coverage.service import CoverageService
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(tags=["覆盖率"])


def get_coverage_service(session: Annotated[Session, Depends(get_db_session)]) -> CoverageService:
    """构造覆盖率分析服务依赖。"""
    return CoverageService(session, CoverageRepository(session))


@router.get(
    "/coverage-reports",
    summary="获取覆盖率报告列表",
    description="分页获取指定生成批次下的覆盖率分析报告，报告会展示课程大纲、教案、试卷题目与课件页面的知识点覆盖矩阵。",
    operation_id="coverage_report_list",
    response_model=ApiResponse[PaginatedData[CoverageReportListItemResponse]],
    status_code=status.HTTP_200_OK,
)
def list_coverage_reports(
    generation_batch_id: int = Query(..., description="生成批次主键", examples=[1]),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    service: Annotated[CoverageService, Depends(get_coverage_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取覆盖率报告列表。"""
    items, total_count = service.list_coverage_reports(
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
        message="获取覆盖率报告列表成功",
    )


@router.get(
    "/coverage-reports/{coverage_report_id}",
    summary="获取覆盖率报告详情",
    description="获取单个覆盖率分析报告的结构化内容。",
    operation_id="coverage_report_detail",
    response_model=ApiResponse[CoverageReportDetailResponse],
    status_code=status.HTTP_200_OK,
)
def get_coverage_report_detail(
    coverage_report_id: int = Path(..., description="覆盖率报告主键", examples=[1]),
    service: Annotated[CoverageService, Depends(get_coverage_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """获取覆盖率报告详情。"""
    detail = service.get_coverage_report_detail(
        owner_user_id=current_user.id,
        coverage_report_id=coverage_report_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "获取覆盖率报告详情成功")


@router.post(
    "/generation-batches/{generation_batch_id}/coverage-reports/refresh",
    summary="重新分析覆盖率报告",
    description="重新汇总指定生成批次下课程大纲、教案、试卷题目与课件页面的知识点引用，并刷新覆盖率报告和质量告警。",
    operation_id="coverage_report_refresh",
    response_model=ApiResponse[CoverageReportDetailResponse],
    status_code=status.HTTP_200_OK,
)
def refresh_coverage_report(
    generation_batch_id: int = Path(..., description="生成批次主键", examples=[1]),
    service: Annotated[CoverageService, Depends(get_coverage_service)] = None,
    current_user: Annotated[SysUser, Depends(get_current_user)] = None,
):
    """重新分析覆盖率报告。"""
    detail = service.refresh_coverage_report(
        owner_user_id=current_user.id,
        generation_batch_id=generation_batch_id,
    )
    return ResponseFactory.success(detail.model_dump(mode="json"), "重新分析覆盖率报告成功")
