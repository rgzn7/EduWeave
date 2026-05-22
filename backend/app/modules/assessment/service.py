"""
@Date: 2026-05-04
@Author: xisy
@Discription: 测评模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import (
    ASSESSMENT_GENERATE_TASK_TYPE,
    ASSESSMENT_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    PAPER_EXPORT_BIZ_TYPE,
    TASK_STATUS_PENDING,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.assessment.presets import resolve_assessment_strategy
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import (
    AssessmentBlueprintDetailResponse,
    AssessmentBlueprintListItemResponse,
    AssessmentTaskCreateRequest,
    PaperResultDetailResponse,
    PaperResultListItemResponse,
    QuestionItemResponse,
)
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.document import DocumentExportService
from app.shared.queue import dispatch_task


class AssessmentService:
    """测评模块服务。"""

    def __init__(self, session: Session, repository: AssessmentRepository | None = None) -> None:
        self.session = session
        self.repository = repository or AssessmentRepository(session)
        self.task_repository = TaskCenterRepository(session)
        self.document_export_service = DocumentExportService(session)

    def create_assessment_task(
        self,
        *,
        owner_user_id: int,
        curriculum_plan_id: int,
        request: AssessmentTaskCreateRequest,
    ) -> TaskListItemResponse:
        """按课程大纲创建测评生成任务。"""
        curriculum_plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在")
        generation_batch = self.repository.get_generation_batch_by_curriculum_plan(curriculum_plan.id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "课程大纲未关联生成批次")
        if not self.repository.list_lesson_plans_by_batch(generation_batch.id):
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "测评生成前必须先完成至少一份教案")

        strategy = resolve_assessment_strategy(request.scene_type.value)
        if self.repository.get_success_paper_result_by_batch_scene(generation_batch.id, strategy["scene_type"]) is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前批次下该测评场景已存在成功试卷")
        if self.repository.get_active_assessment_task(generation_batch.id, strategy["scene_type"]) is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前批次下该测评场景已有运行中的测评任务")

        task = self._create_assessment_task_record(
            generation_batch=generation_batch,
            curriculum_plan_id=curriculum_plan.id,
            strategy=strategy,
            owner_user_id=owner_user_id,
        )
        self.session.commit()
        dispatch_result = dispatch_task(
            "app.modules.assessment.tasks.run_generate_assessment_task",
            {
                "task_record_id": task.id,
                "generation_batch_id": generation_batch.id,
                "curriculum_plan_id": curriculum_plan.id,
                "scene_type": strategy["scene_type"],
                "operator_user_id": owner_user_id,
            },
            queue=GENERATION_QUEUE_NAME,
            session=self.session,
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

        self.session.expire_all()
        fresh_task = self.task_repository.get_task_by_id(task.id)
        return TaskCenterService.build_task_list_item(fresh_task)

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

    def export_paper_result_docx(self, *, owner_user_id: int, paper_result_id: int) -> FileDownloadUrlResponse:
        """导出试卷结果 DOCX。"""
        paper_result = self.repository.get_paper_result_for_owner(paper_result_id, owner_user_id)
        if paper_result is None:
            raise AppException(BusinessErrorCode.PAPER_RESULT_NOT_FOUND, "试卷结果不存在")
        generation_batch = self.repository.get_generation_batch(paper_result.generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        questions = self.repository.list_question_items(paper_result.id)
        content = self.document_export_service.render_service.render_paper_result(paper_result, questions)
        return self.document_export_service.archive_docx(
            project_id=generation_batch.project_id,
            owner_user_id=owner_user_id,
            biz_type=PAPER_EXPORT_BIZ_TYPE,
            object_segments=(str(generation_batch.project_id), "exports", "paper-results", str(paper_result.id)),
            filename="paper.docx",
            content=content,
            metadata_json={
                "paper_result_id": paper_result.id,
                "generation_batch_id": paper_result.generation_batch_id,
                "assessment_blueprint_id": paper_result.assessment_blueprint_id,
                "scene_type": paper_result.scene_type,
            },
            target=paper_result,
        )

    @staticmethod
    def build_assessment_blueprint_response(blueprint) -> AssessmentBlueprintListItemResponse:
        """构造测评蓝图响应。"""
        return AssessmentBlueprintListItemResponse.model_validate(blueprint, from_attributes=True)

    @staticmethod
    def build_paper_result_response(paper_result) -> PaperResultListItemResponse:
        """构造试卷结果响应。"""
        return PaperResultListItemResponse.model_validate(paper_result, from_attributes=True)

    def _create_assessment_task_record(
        self,
        *,
        generation_batch,
        curriculum_plan_id: int,
        strategy: dict,
        owner_user_id: int | None,
    ):
        """创建测评生成任务记录。"""
        task = self.task_repository.create_task(
            project_id=generation_batch.project_id,
            generation_batch_id=generation_batch.id,
            module_code=ASSESSMENT_MODULE_CODE,
            task_type=ASSESSMENT_GENERATE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=GENERATION_QUEUE_NAME,
            biz_key=f"generation_batch:{generation_batch.id}:assessment:{strategy['scene_type']}",
            operator_user_id=owner_user_id,
            payload_json={
                "generation_batch_id": generation_batch.id,
                "curriculum_plan_id": curriculum_plan_id,
                "scene_type": strategy["scene_type"],
            },
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_assessment_baseline", "准备测评生成基线"),
            ("invoke_llm_assessment", "调用 LLM 生成测评"),
            ("persist_assessment_result", "落库测评蓝图与试卷"),
            ("finalize_assessment_task", "完成测评任务"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        return task
