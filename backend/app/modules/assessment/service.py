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
from app.modules.assessment.presets import ASSESSMENT_SCENE_PRESETS, SceneType, resolve_assessment_strategy
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import (
    AssessmentBlueprintDetailResponse,
    AssessmentBlueprintListItemResponse,
    AssessmentTaskCreateRequest,
    PaperResultDetailResponse,
    PaperResultListItemResponse,
    QuestionItemListItemResponse,
    QuestionItemResponse,
)
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.p0_models import PaperResult, QuestionItem
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.document import DocumentExportService
from app.shared.document.naming import build_docx_filename, strip_lesson_prefix
from app.shared.queue import dispatch_task
from app.shared.question_basis import (
    build_question_basis,
    extract_first_teaching_goal,
    find_lesson_plan_for_knowledge_point,
    index_blueprint_kp_weights,
)


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
        if request.scene_type == SceneType.HOMEWORK:
            raise AppException(
                BusinessErrorCode.ASSESSMENT_SCENE_INVALID,
                "课后作业请通过 /lesson-plans/{lesson_plan_id}/homework-tasks 创建",
                {"scene_type": request.scene_type.value},
            )
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

    def list_question_items(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int | None,
        paper_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
        scene_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[QuestionItemListItemResponse], int]:
        """分页查询题库题目列表。"""
        if generation_batch_id is not None:
            if self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id) is None:
                raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if paper_result_id is not None:
            if self.repository.get_paper_result_for_owner(paper_result_id, owner_user_id) is None:
                raise AppException(BusinessErrorCode.PAPER_RESULT_NOT_FOUND, "试卷结果不存在")

        offset = (page - 1) * page_size
        rows = self.repository.list_question_items_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            paper_result_id=paper_result_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            difficulty_level=difficulty_level,
            scene_type=scene_type,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_question_items_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            paper_result_id=paper_result_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            difficulty_level=difficulty_level,
            scene_type=scene_type,
        )
        # 同一试卷共享一份蓝图与批次，先按试卷分组以便批量装配考查依据
        questions_by_paper: dict[int, list[QuestionItem]] = {}
        paper_lookup: dict[int, PaperResult] = {}
        for question_item, paper_result in rows:
            questions_by_paper.setdefault(paper_result.id, []).append(question_item)
            paper_lookup[paper_result.id] = paper_result

        enriched_by_question_id: dict[int, QuestionItemResponse] = {}
        for paper_id, grouped_questions in questions_by_paper.items():
            enriched = self._build_question_items_with_basis(paper_lookup[paper_id], grouped_questions)
            for question_response in enriched:
                enriched_by_question_id[question_response.id] = question_response

        items: list[QuestionItemListItemResponse] = []
        for question_item, paper_result in rows:
            question_response = enriched_by_question_id[question_item.id]
            items.append(
                QuestionItemListItemResponse(
                    **question_response.model_dump(),
                    paper_title=paper_result.title,
                    scene_type=paper_result.scene_type,
                )
            )
        return items, total_count

    def get_paper_result_detail(self, *, owner_user_id: int, paper_result_id: int) -> PaperResultDetailResponse:
        """查询试卷结果详情。"""
        paper_result = self.repository.get_paper_result_for_owner(paper_result_id, owner_user_id)
        if paper_result is None:
            raise AppException(BusinessErrorCode.PAPER_RESULT_NOT_FOUND, "试卷结果不存在")
        questions = self._build_question_items_with_basis(
            paper_result,
            self.repository.list_question_items(paper_result.id),
        )
        return PaperResultDetailResponse(
            **self.build_paper_result_response(paper_result).model_dump(),
            questions=questions,
        )

    def _build_question_items_with_basis(
        self,
        paper_result: PaperResult,
        question_items: list[QuestionItem],
    ) -> list[QuestionItemResponse]:
        """为测评题目装配 knowledge_point_name 与 question_basis_json。"""
        if not question_items:
            return []
        knowledge_point_ids = {q.knowledge_point_id for q in question_items if q.knowledge_point_id is not None}
        knowledge_points = {
            kp.id: kp for kp in self.repository.list_knowledge_points_by_ids(list(knowledge_point_ids))
        }
        chapter_node_ids = [
            kp.chapter_node_id for kp in knowledge_points.values() if kp.chapter_node_id is not None
        ]
        chapter_nodes = {
            node.id: node for node in self.repository.list_chapter_nodes_by_ids(chapter_node_ids)
        }
        blueprint = self.repository.get_assessment_blueprint(paper_result.assessment_blueprint_id)
        blueprint_kp_weights = index_blueprint_kp_weights(blueprint.content_json if blueprint else None)
        # 在批次内查找首个覆盖该知识点的课次，缺批次则降级为空列表
        lesson_plans = self.repository.list_lesson_plans_by_batch(paper_result.generation_batch_id)

        responses: list[QuestionItemResponse] = []
        for question in question_items:
            base = QuestionItemResponse.model_validate(question, from_attributes=True)
            knowledge_point = knowledge_points.get(question.knowledge_point_id) if question.knowledge_point_id else None
            chapter_node = (
                chapter_nodes.get(knowledge_point.chapter_node_id)
                if knowledge_point and knowledge_point.chapter_node_id is not None
                else None
            )
            lesson_plan = (
                find_lesson_plan_for_knowledge_point(lesson_plans, knowledge_point.id) if knowledge_point else None
            )
            teaching_goal = extract_first_teaching_goal(lesson_plan.content_json if lesson_plan else None)
            # 优先使用持久化的 question_basis_json，DB 为空时回退到实时聚合（兼容历史数据）
            basis = question.question_basis_json or build_question_basis(
                scene="assessment",
                knowledge_point=knowledge_point,
                chapter_node=chapter_node,
                lesson_plan=lesson_plan,
                teaching_goal=teaching_goal,
                difficulty_level=question.difficulty_level,
                blueprint_kp_weights=blueprint_kp_weights,
                blueprint_type="assessment",
                blueprint_id=paper_result.assessment_blueprint_id,
            )
            responses.append(
                base.model_copy(
                    update={
                        "knowledge_point_name": knowledge_point.point_name if knowledge_point else None,
                        "question_basis_json": basis,
                    }
                )
            )
        return responses

    def export_paper_result_docx(self, *, owner_user_id: int, paper_result_id: int) -> FileDownloadUrlResponse:
        """导出试卷结果 DOCX。"""
        paper_result = self.repository.get_paper_result_for_owner(paper_result_id, owner_user_id)
        if paper_result is None:
            raise AppException(BusinessErrorCode.PAPER_RESULT_NOT_FOUND, "试卷结果不存在")
        generation_batch = self.repository.get_generation_batch(paper_result.generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        questions = self._build_question_items_with_basis(
            paper_result,
            self.repository.list_question_items(paper_result.id),
        )
        content = self.document_export_service.render_service.render_paper_result(paper_result, questions)
        scene_preset = ASSESSMENT_SCENE_PRESETS.get(paper_result.scene_type)
        scene_label = scene_preset["scene_label"] if scene_preset else (paper_result.scene_type or "测评")
        filename = build_docx_filename(
            strip_lesson_prefix(paper_result.title),
            scene_label,
            fallback=scene_label,
        )
        return self.document_export_service.archive_docx(
            project_id=generation_batch.project_id,
            owner_user_id=owner_user_id,
            biz_type=PAPER_EXPORT_BIZ_TYPE,
            object_segments=(str(generation_batch.project_id), "exports", "paper-results", str(paper_result.id)),
            filename=filename,
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
