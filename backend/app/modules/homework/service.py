"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import (
    GENERATION_QUEUE_NAME,
    HOMEWORK_EXPORT_BIZ_TYPE,
    HOMEWORK_GENERATE_TASK_TYPE,
    HOMEWORK_MODULE_CODE,
    TASK_STATUS_PENDING,
    VERSION_STATUS_READY,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.homework.presets import resolve_homework_strategy
from app.modules.homework.repository import HomeworkRepository
from app.modules.homework.schemas import (
    HomeworkBlueprintResponse,
    HomeworkQuestionListItemResponse,
    HomeworkQuestionResponse,
    HomeworkResultDetailResponse,
    HomeworkResultListItemResponse,
)
from app.modules.p0_models import HomeworkQuestion, HomeworkResult, LessonPlan
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.document import DocumentExportService
from app.shared.document.naming import build_docx_filename, strip_lesson_prefix
from app.shared.queue import dispatch_task
from app.shared.question_basis import (
    build_question_basis,
    extract_first_teaching_goal,
    index_blueprint_kp_weights,
)


class HomeworkService:
    """课后作业模块服务。"""

    def __init__(self, session: Session, repository: HomeworkRepository | None = None) -> None:
        self.session = session
        self.repository = repository or HomeworkRepository(session)
        self.task_repository = TaskCenterRepository(session)
        self.document_export_service = DocumentExportService(session)

    def create_homework_task(
        self,
        *,
        owner_user_id: int,
        lesson_plan_id: int,
        regenerate: bool = False,
    ) -> TaskListItemResponse:
        """按教案创建课后作业生成任务。

        regenerate=True 时为「重新生成」：跳过「已存在成功作业」拦截，生成成功后由 worker
        在同一事务内整体覆盖旧作业；仍保留「已有运行中任务」拦截以避免并发重复触发。
        """
        lesson_plan = self.repository.get_lesson_plan_for_owner(lesson_plan_id, owner_user_id)
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        if lesson_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案版本不可用")
        if lesson_plan.generation_batch_id is None:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "教案未关联生成批次")

        generation_batch = self.repository.get_generation_batch(lesson_plan.generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")

        # 重新生成时允许覆盖既有成功作业，故跳过该拦截；防并发的运行中任务拦截始终保留
        if not regenerate and self.repository.get_success_homework_result_by_lesson(lesson_plan.id) is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前教案已存在成功的课后作业")
        if self.repository.get_active_homework_task(lesson_plan.id) is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前教案已有运行中的作业生成任务")

        strategy = resolve_homework_strategy()
        task = self._create_homework_task_record(
            generation_batch=generation_batch,
            lesson_plan=lesson_plan,
            strategy=strategy,
            owner_user_id=owner_user_id,
        )
        self.session.commit()
        dispatch_result = dispatch_task(
            "app.modules.homework.tasks.run_generate_homework_task",
            {
                "task_record_id": task.id,
                "generation_batch_id": generation_batch.id,
                "lesson_plan_id": lesson_plan.id,
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

    def list_homework_results(
        self,
        *,
        owner_user_id: int,
        curriculum_plan_id: int | None,
        generation_batch_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[HomeworkResultListItemResponse], int]:
        """分页查询作业结果列表。"""
        offset = (page - 1) * page_size
        rows = self.repository.list_homework_results_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
            generation_batch_id=generation_batch_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_homework_results_for_owner(
            owner_user_id,
            curriculum_plan_id=curriculum_plan_id,
            generation_batch_id=generation_batch_id,
        )
        return [self._build_result_list_item(result, lesson_plan) for result, lesson_plan in rows], total_count

    def get_homework_result_detail(
        self,
        *,
        owner_user_id: int,
        homework_result_id: int,
    ) -> HomeworkResultDetailResponse:
        """按主键查询作业结果详情。"""
        homework_result = self.repository.get_homework_result_for_owner(homework_result_id, owner_user_id)
        if homework_result is None:
            raise AppException(BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND, "课后作业不存在")
        lesson_plan = self.repository.get_lesson_plan(homework_result.lesson_plan_id)
        return self._build_result_detail(homework_result, lesson_plan)

    def get_homework_result_detail_by_lesson(
        self,
        *,
        owner_user_id: int,
        lesson_plan_id: int,
    ) -> HomeworkResultDetailResponse:
        """按教案查询作业结果详情。"""
        lesson_plan = self.repository.get_lesson_plan_for_owner(lesson_plan_id, owner_user_id)
        if lesson_plan is None:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        homework_result = self.repository.get_homework_result_by_lesson(lesson_plan_id)
        if homework_result is None:
            raise AppException(BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND, "课后作业不存在")
        return self._build_result_detail(homework_result, lesson_plan)

    def get_homework_blueprint_detail(
        self,
        *,
        owner_user_id: int,
        homework_blueprint_id: int,
    ) -> HomeworkBlueprintResponse:
        """查询作业蓝图详情。"""
        blueprint = self.repository.get_homework_blueprint_for_owner(homework_blueprint_id, owner_user_id)
        if blueprint is None:
            raise AppException(BusinessErrorCode.HOMEWORK_BLUEPRINT_NOT_FOUND, "课后作业蓝图不存在")
        return HomeworkBlueprintResponse.model_validate(blueprint, from_attributes=True)

    def list_homework_questions(
        self,
        *,
        owner_user_id: int,
        lesson_plan_id: int | None,
        homework_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[HomeworkQuestionListItemResponse], int]:
        """分页查询作业题目列表。"""
        if lesson_plan_id is not None:
            if self.repository.get_lesson_plan_for_owner(lesson_plan_id, owner_user_id) is None:
                raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在")
        if homework_result_id is not None:
            if self.repository.get_homework_result_for_owner(homework_result_id, owner_user_id) is None:
                raise AppException(BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND, "课后作业不存在")

        offset = (page - 1) * page_size
        rows = self.repository.list_homework_questions_for_owner(
            owner_user_id,
            lesson_plan_id=lesson_plan_id,
            homework_result_id=homework_result_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            difficulty_level=difficulty_level,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_homework_questions_for_owner(
            owner_user_id,
            lesson_plan_id=lesson_plan_id,
            homework_result_id=homework_result_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            difficulty_level=difficulty_level,
        )
        # 同一作业共享一份蓝图与教案，先按作业分组以便批量装配考查依据
        questions_by_result: dict[int, list[HomeworkQuestion]] = {}
        result_lookup: dict[int, HomeworkResult] = {}
        lesson_plan_lookup: dict[int, LessonPlan] = {}
        for question, homework_result, lesson_plan in rows:
            questions_by_result.setdefault(homework_result.id, []).append(question)
            result_lookup[homework_result.id] = homework_result
            lesson_plan_lookup[homework_result.id] = lesson_plan

        enriched_by_question_id: dict[int, HomeworkQuestionResponse] = {}
        for result_id, grouped_questions in questions_by_result.items():
            enriched = self._build_question_items_with_basis(
                result_lookup[result_id],
                lesson_plan_lookup[result_id],
                grouped_questions,
            )
            for question_response in enriched:
                enriched_by_question_id[question_response.id] = question_response

        items: list[HomeworkQuestionListItemResponse] = []
        for question, homework_result, lesson_plan in rows:
            question_response = enriched_by_question_id[question.id]
            items.append(
                HomeworkQuestionListItemResponse(
                    **question_response.model_dump(),
                    homework_title=homework_result.title,
                    class_session_no=lesson_plan.class_session_no,
                )
            )
        return items, total_count

    def export_homework_result_docx(
        self,
        *,
        owner_user_id: int,
        homework_result_id: int,
    ) -> FileDownloadUrlResponse:
        """导出作业结果 DOCX。"""
        homework_result = self.repository.get_homework_result_for_owner(homework_result_id, owner_user_id)
        if homework_result is None:
            raise AppException(BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND, "课后作业不存在")
        generation_batch = self.repository.get_generation_batch(homework_result.generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        lesson_plan = self.repository.get_lesson_plan(homework_result.lesson_plan_id)
        questions = self._build_question_items_with_basis(
            homework_result,
            lesson_plan,
            self.repository.list_homework_questions(homework_result.id),
        )
        content = self.document_export_service.render_service.render_homework_result(
            homework_result,
            questions,
            lesson_plan=lesson_plan,
        )
        title_segment = strip_lesson_prefix(
            (lesson_plan.lesson_title if lesson_plan and lesson_plan.lesson_title else homework_result.title)
        )
        session_segment = (
            f"第{lesson_plan.class_session_no}讲"
            if lesson_plan and lesson_plan.class_session_no is not None
            else None
        )
        filename = build_docx_filename(title_segment, session_segment, "课后作业", fallback="课后作业")
        return self.document_export_service.archive_docx(
            project_id=generation_batch.project_id,
            owner_user_id=owner_user_id,
            biz_type=HOMEWORK_EXPORT_BIZ_TYPE,
            object_segments=(str(generation_batch.project_id), "exports", "homework-results", str(homework_result.id)),
            filename=filename,
            content=content,
            metadata_json={
                "homework_result_id": homework_result.id,
                "homework_blueprint_id": homework_result.homework_blueprint_id,
                "generation_batch_id": homework_result.generation_batch_id,
                "lesson_plan_id": homework_result.lesson_plan_id,
                "class_session_no": lesson_plan.class_session_no if lesson_plan else None,
            },
            target=homework_result,
        )

    def _create_homework_task_record(
        self,
        *,
        generation_batch,
        lesson_plan: LessonPlan,
        strategy: dict,
        owner_user_id: int | None,
    ):
        """创建课后作业生成任务记录。"""
        task = self.task_repository.create_task(
            project_id=generation_batch.project_id,
            generation_batch_id=generation_batch.id,
            module_code=HOMEWORK_MODULE_CODE,
            task_type=HOMEWORK_GENERATE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=GENERATION_QUEUE_NAME,
            biz_key=f"lesson_plan:{lesson_plan.id}:homework",
            operator_user_id=owner_user_id,
            payload_json={
                "generation_batch_id": generation_batch.id,
                "lesson_plan_id": lesson_plan.id,
                "strategy": strategy,
            },
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_homework_baseline", "准备课后作业生成基线"),
            ("invoke_llm_homework", "调用 LLM 生成课后作业"),
            ("persist_homework_result", "落库作业蓝图与作业结果"),
            ("finalize_homework_task", "完成课后作业任务"),
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

    def _build_result_list_item(
        self,
        homework_result: HomeworkResult,
        lesson_plan: LessonPlan | None,
    ) -> HomeworkResultListItemResponse:
        """构造作业结果列表项。"""
        base = HomeworkResultListItemResponse.model_validate(homework_result, from_attributes=True)
        return base.model_copy(
            update={
                "class_session_no": lesson_plan.class_session_no if lesson_plan else None,
                "lesson_title": lesson_plan.lesson_title if lesson_plan else None,
            }
        )

    def _build_result_detail(
        self,
        homework_result: HomeworkResult,
        lesson_plan: LessonPlan | None,
    ) -> HomeworkResultDetailResponse:
        """构造作业结果详情。"""
        questions = self._build_question_items_with_basis(
            homework_result,
            lesson_plan,
            self.repository.list_homework_questions(homework_result.id),
        )
        base = HomeworkResultDetailResponse.model_validate(homework_result, from_attributes=True)
        return base.model_copy(
            update={
                "class_session_no": lesson_plan.class_session_no if lesson_plan else None,
                "lesson_title": lesson_plan.lesson_title if lesson_plan else None,
                "questions": questions,
            }
        )

    def _build_question_items_with_basis(
        self,
        homework_result: HomeworkResult,
        lesson_plan: LessonPlan | None,
        homework_questions: list[HomeworkQuestion],
    ) -> list[HomeworkQuestionResponse]:
        """为作业题目装配 knowledge_point_name 与 question_basis_json。"""
        if not homework_questions:
            return []
        knowledge_point_ids = {q.knowledge_point_id for q in homework_questions if q.knowledge_point_id is not None}
        knowledge_points = {
            kp.id: kp for kp in self.repository.list_knowledge_points_by_ids(list(knowledge_point_ids))
        }
        chapter_node_ids = [
            kp.chapter_node_id for kp in knowledge_points.values() if kp.chapter_node_id is not None
        ]
        chapter_nodes = {
            node.id: node for node in self.repository.list_chapter_nodes_by_ids(chapter_node_ids)
        }
        blueprint = self.repository.get_homework_blueprint(homework_result.homework_blueprint_id)
        blueprint_kp_weights = index_blueprint_kp_weights(blueprint.content_json if blueprint else None)
        teaching_goal = extract_first_teaching_goal(lesson_plan.content_json if lesson_plan else None)

        responses: list[HomeworkQuestionResponse] = []
        for question in homework_questions:
            base = HomeworkQuestionResponse.model_validate(question, from_attributes=True)
            knowledge_point = knowledge_points.get(question.knowledge_point_id) if question.knowledge_point_id else None
            chapter_node = (
                chapter_nodes.get(knowledge_point.chapter_node_id)
                if knowledge_point and knowledge_point.chapter_node_id is not None
                else None
            )
            # 优先使用持久化的 question_basis_json，DB 为空时回退到实时聚合（兼容历史数据）
            basis = question.question_basis_json or build_question_basis(
                scene="homework",
                knowledge_point=knowledge_point,
                chapter_node=chapter_node,
                lesson_plan=lesson_plan,
                teaching_goal=teaching_goal,
                difficulty_level=question.difficulty_level,
                blueprint_kp_weights=blueprint_kp_weights,
                blueprint_type="homework",
                blueprint_id=homework_result.homework_blueprint_id,
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
