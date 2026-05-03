"""
@Date: 2026-04-29
@Author: xisy
@Discription: 测评模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import (
    AssessmentBlueprintDetailResponse,
    AssessmentBlueprintListItemResponse,
    PaperResultDetailResponse,
    PaperResultListItemResponse,
    QuestionItemResponse,
)


class AssessmentService:
    """测评模块服务。"""

    def __init__(self, session: Session, repository: AssessmentRepository | None = None) -> None:
        self.session = session
        self.repository = repository or AssessmentRepository(session)

    def list_assessment_blueprints(
        self,
        *,
        owner_user_id: int,
        curriculum_plan_id: int,
        scenario_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AssessmentBlueprintListItemResponse], int]:
        """分页查询测评蓝图列表。"""
        curriculum_plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        offset = (page - 1) * page_size
        blueprints = self.repository.list_assessment_blueprints_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
            scenario_type=scenario_type,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_assessment_blueprints_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
            scenario_type=scenario_type,
        )
        return [self.build_assessment_blueprint_response(blueprint) for blueprint in blueprints], total_count

    def get_assessment_blueprint_detail(
        self,
        *,
        owner_user_id: int,
        assessment_blueprint_id: int,
    ) -> AssessmentBlueprintDetailResponse:
        """查询测评蓝图详情。"""
        blueprint = self.repository.get_assessment_blueprint_for_owner(assessment_blueprint_id, owner_user_id)
        if blueprint is None:
            raise AppException(BusinessErrorCode.ASSESSMENT_BLUEPRINT_NOT_FOUND, "测评蓝图不存在")
        return AssessmentBlueprintDetailResponse(**self.build_assessment_blueprint_response(blueprint).model_dump())

    def list_paper_results(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int,
        scene_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[PaperResultListItemResponse], int]:
        """分页查询试卷结果列表。"""
        generation_batch = self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        offset = (page - 1) * page_size
        paper_results = self.repository.list_paper_results_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            scene_type=scene_type,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_paper_results_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            scene_type=scene_type,
        )
        return [self.build_paper_result_response(paper_result) for paper_result in paper_results], total_count

    def get_paper_result_detail(self, *, owner_user_id: int, paper_result_id: int) -> PaperResultDetailResponse:
        """查询试卷结果详情。"""
        paper_result = self.repository.get_paper_result_for_owner(paper_result_id, owner_user_id)
        if paper_result is None:
            raise AppException(BusinessErrorCode.PAPER_RESULT_NOT_FOUND, "试卷结果不存在")
        questions = [
            QuestionItemResponse.model_validate(question, from_attributes=True)
            for question in self.repository.list_question_items(paper_result.id)
        ]
        return PaperResultDetailResponse(
            **self.build_paper_result_response(paper_result).model_dump(),
            questions=questions,
        )

    @staticmethod
    def build_assessment_blueprint_response(blueprint) -> AssessmentBlueprintListItemResponse:
        """构造测评蓝图响应。"""
        return AssessmentBlueprintListItemResponse.model_validate(blueprint, from_attributes=True)

    @staticmethod
    def build_paper_result_response(paper_result) -> PaperResultListItemResponse:
        """构造试卷结果响应。"""
        return PaperResultListItemResponse.model_validate(paper_result, from_attributes=True)
