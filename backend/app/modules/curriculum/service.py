"""
@Date: 2026-04-26
@Author: xisy
@Discription: 课程大纲模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import CURRICULUM_EXPORT_BIZ_TYPE
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.schemas import CurriculumPlanDetailResponse, CurriculumPlanListItemResponse
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.shared.document import DocumentExportService


class CurriculumService:
    """课程大纲模块服务。"""

    def __init__(self, session: Session, repository: CurriculumRepository | None = None) -> None:
        self.session = session
        self.repository = repository or CurriculumRepository(session)
        self.document_export_service = DocumentExportService(session)

    def list_curriculum_plans(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        knowledge_version_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CurriculumPlanListItemResponse], int]:
        """分页查询课程大纲列表。"""
        offset = (page - 1) * page_size
        plans = self.repository.list_curriculum_plans_for_owner(
            owner_user_id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_curriculum_plans_for_owner(
            owner_user_id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        return [self.build_curriculum_plan_response(plan) for plan in plans], total_count

    def get_curriculum_plan_detail(self, *, owner_user_id: int, curriculum_plan_id: int) -> CurriculumPlanDetailResponse:
        """查询课程大纲详情。"""
        plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        return CurriculumPlanDetailResponse(**self.build_curriculum_plan_response(plan).model_dump())

    def export_curriculum_plan_docx(self, *, owner_user_id: int, curriculum_plan_id: int) -> FileDownloadUrlResponse:
        """导出课程大纲 DOCX。"""
        plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        content = self.document_export_service.render_service.render_curriculum_plan(plan)
        return self.document_export_service.archive_docx(
            project_id=plan.project_id,
            owner_user_id=owner_user_id,
            biz_type=CURRICULUM_EXPORT_BIZ_TYPE,
            object_segments=(str(plan.project_id), "exports", "curriculum-plans", str(plan.id)),
            filename=f"v{plan.version_no}.docx",
            content=content,
            metadata_json={"curriculum_plan_id": plan.id, "version_no": plan.version_no},
            target=plan,
        )

    @staticmethod
    def build_curriculum_plan_response(plan) -> CurriculumPlanListItemResponse:
        """构造课程大纲响应。"""
        return CurriculumPlanListItemResponse.model_validate(plan, from_attributes=True)
