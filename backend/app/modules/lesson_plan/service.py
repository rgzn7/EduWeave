"""
@Date: 2026-04-26
@Author: xisy
@Discription: 教案模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanDetailResponse, LessonPlanListItemResponse


class LessonPlanService:
    """教案模块服务。"""

    def __init__(self, session: Session, repository: LessonPlanRepository | None = None) -> None:
        self.session = session
        self.repository = repository or LessonPlanRepository(session)

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

    @staticmethod
    def build_lesson_plan_response(lesson_plan) -> LessonPlanListItemResponse:
        """构造教案响应。"""
        return LessonPlanListItemResponse.model_validate(lesson_plan, from_attributes=True)

