"""
@Date: 2026-04-26
@Author: xisy
@Discription: 教案模块业务服务
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import LESSON_PLAN_EXPORT_BIZ_TYPE
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanDetailResponse, LessonPlanListItemResponse
from app.shared.document import DocumentExportService
from app.shared.document.naming import build_docx_filename, strip_lesson_prefix


class LessonPlanService:
    """教案模块服务。"""

    def __init__(self, session: Session, repository: LessonPlanRepository | None = None) -> None:
        self.session = session
        self.repository = repository or LessonPlanRepository(session)
        self.document_export_service = DocumentExportService(session)

    def list_lesson_plans(
        self,
        *,
        owner_user_id: int,
        curriculum_plan_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[LessonPlanListItemResponse], int]:
        """分页查询教案列表。"""
        curriculum_plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        offset = (page - 1) * page_size
        lesson_plans = self.repository.list_lesson_plans_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_lesson_plans_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
        )
        return [self.build_lesson_plan_response(lesson_plan) for lesson_plan in lesson_plans], total_count

    def get_lesson_plan_detail(self, *, owner_user_id: int, lesson_plan_id: int) -> LessonPlanDetailResponse:
        """查询教案详情。"""
        lesson_plan = self.repository.get_lesson_plan_for_owner(lesson_plan_id, owner_user_id)
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        return LessonPlanDetailResponse(**self.build_lesson_plan_response(lesson_plan).model_dump())

    def export_lesson_plan_docx(self, *, owner_user_id: int, lesson_plan_id: int) -> FileDownloadUrlResponse:
        """导出教案 DOCX。"""
        lesson_plan = self.repository.get_lesson_plan_for_owner(lesson_plan_id, owner_user_id)
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        curriculum_plan = self.repository.get_curriculum_plan(lesson_plan.curriculum_plan_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        knowledge_point_names = self._collect_knowledge_point_names(lesson_plan.content_json)
        content = self.document_export_service.render_service.render_lesson_plan(
            lesson_plan,
            knowledge_point_names=knowledge_point_names,
        )
        session_segment = (
            f"第{lesson_plan.class_session_no}讲" if lesson_plan.class_session_no is not None else None
        )
        filename = build_docx_filename(
            strip_lesson_prefix(lesson_plan.lesson_title),
            session_segment,
            "教案",
            fallback="教案",
        )
        return self.document_export_service.archive_docx(
            project_id=curriculum_plan.project_id,
            owner_user_id=owner_user_id,
            biz_type=LESSON_PLAN_EXPORT_BIZ_TYPE,
            object_segments=(str(curriculum_plan.project_id), "exports", "lesson-plans", str(lesson_plan.id)),
            filename=filename,
            content=content,
            metadata_json={
                "lesson_plan_id": lesson_plan.id,
                "curriculum_plan_id": lesson_plan.curriculum_plan_id,
                "version_no": lesson_plan.version_no,
                "class_session_no": lesson_plan.class_session_no,
            },
            target=lesson_plan,
        )

    def _collect_knowledge_point_names(self, content_json: Any) -> dict[int, str]:
        """从教案结构化内容收集所有 knowledge_point_refs 并解析成 id -> name。"""
        ids: set[int] = set()
        content = content_json if isinstance(content_json, dict) else {}
        for ref in content.get("knowledge_point_refs") or []:
            _accumulate_int(ref, ids)
        for step in content.get("teaching_flow") or []:
            if isinstance(step, dict):
                for ref in step.get("knowledge_point_refs") or []:
                    _accumulate_int(ref, ids)
        for session_plan in content.get("session_plans") or []:
            if not isinstance(session_plan, dict):
                continue
            for ref in session_plan.get("knowledge_point_refs") or []:
                _accumulate_int(ref, ids)
            for step in session_plan.get("teaching_steps") or []:
                if isinstance(step, dict):
                    for ref in step.get("knowledge_point_refs") or []:
                        _accumulate_int(ref, ids)
        if not ids:
            return {}
        records = self.repository.list_knowledge_points_by_ids(list(ids))
        return {record.id: record.point_name for record in records}

    @staticmethod
    def build_lesson_plan_response(lesson_plan) -> LessonPlanListItemResponse:
        """构造教案响应。"""
        return LessonPlanListItemResponse.model_validate(lesson_plan, from_attributes=True)


def _accumulate_int(value: Any, target: set[int]) -> None:
    """安全把可转 int 的引用加入集合，转换失败时跳过。"""
    try:
        target.add(int(value))
    except (TypeError, ValueError):
        return
