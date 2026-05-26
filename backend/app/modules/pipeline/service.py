"""
@Date: 2026-05-03
@Author: xisy
@Discription: 生成编排模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import (
    CURRICULUM_GENERATE_TASK_TYPE,
    CURRICULUM_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    TASK_STATUS_PENDING,
    VERSION_STATUS_READY,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.assessment.presets import DEFAULT_ASSESSMENT_SCENE_TYPE, resolve_assessment_strategy
from app.modules.p0_models import GenerationBatch
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import (
    GenerationBatchCreateRequest,
    GenerationBatchDetailResponse,
    GenerationBatchListItemResponse,
)
from app.modules.task_center.heartbeat import dispatch_with_attempt
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.service import TaskCenterService
from app.shared.utils import DateTimeUtil


class PipelineService:
    """生成编排模块服务。"""

    def __init__(self, session: Session, repository: PipelineRepository | None = None) -> None:
        self.session = session
        self.repository = repository or PipelineRepository(session)
        self.task_repository = TaskCenterRepository(session)

    def create_generation_batch(
        self,
        *,
        owner_user_id: int,
        request: GenerationBatchCreateRequest,
        generation_run_id: int | None = None,
    ) -> GenerationBatchDetailResponse:
        """创建生成批次并投递课程大纲生成任务。

        generation_run_id 由 OrchestratorService 在一键生成场景注入，会随每个下游任务的
        payload_json 携带，使任务 success/failure 钩子能反查回 run 状态。
        """
        project = self.repository.get_project_for_owner(request.project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        knowledge_version = self.repository.get_knowledge_version_in_project(project.id, request.knowledge_version_id)
        if knowledge_version is None or knowledge_version.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "知识版本不属于当前项目或不可用")

        profile_version = self.repository.get_learner_profile_version_in_project(
            project.id,
            request.learner_profile_version_id,
        )
        if (
            profile_version is None
            or profile_version.version_status != VERSION_STATUS_READY
            or profile_version.extract_status != "success"
        ):
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "学情版本不属于当前项目或不可用")

        generation_batch = self.repository.create_generation_batch(
            GenerationBatch(
                project_id=project.id,
                batch_no=self.repository.get_next_batch_no(project.id),
                batch_name=request.batch_name,
                trigger_mode="manual",
                batch_status=TASK_STATUS_PENDING,
                knowledge_version_id=knowledge_version.id,
                learner_profile_version_id=profile_version.id,
                chapter_range_json=request.chapter_range_json,
                course_count=request.course_count,
                session_duration_minutes=request.session_duration_minutes,
                assessment_strategy_json=resolve_assessment_strategy(DEFAULT_ASSESSMENT_SCENE_TYPE),
                pipeline_options_json={"enabled_steps": ["curriculum", "lesson_plan", "coverage"]},
                created_by=owner_user_id,
            )
        )
        project.latest_generation_batch_id = generation_batch.id
        project.last_activity_at = DateTimeUtil.now_utc()
        self.repository.save(project)
        task = self._create_curriculum_task(
            generation_batch=generation_batch,
            owner_user_id=owner_user_id,
            request=request,
            generation_run_id=generation_run_id,
        )
        self.session.commit()

        dispatch_payload: dict[str, object] = {
            "task_record_id": task.id,
            "generation_batch_id": generation_batch.id,
            "operator_user_id": owner_user_id,
        }
        if generation_run_id is not None:
            dispatch_payload["generation_run_id"] = generation_run_id
        dispatch_result = dispatch_with_attempt(
            self.task_repository,
            task=task,
            callable_path="app.modules.curriculum.tasks.run_generate_curriculum_task",
            payload=dispatch_payload,
            queue=GENERATION_QUEUE_NAME,
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

        self.session.expire_all()
        return self.get_generation_batch_detail(
            owner_user_id=owner_user_id,
            generation_batch_id=generation_batch.id,
        )

    def list_generation_batches(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[GenerationBatchListItemResponse], int]:
        """分页查询生成批次。"""
        project = self.repository.get_project_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        offset = (page - 1) * page_size
        batches = self.repository.list_generation_batches_for_owner(
            owner_user_id,
            project_id=project_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_generation_batches_for_owner(owner_user_id, project_id=project_id)
        return [self.build_generation_batch_list_item(batch) for batch in batches], total_count

    def get_generation_batch_detail(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int,
    ) -> GenerationBatchDetailResponse:
        """查询生成批次详情。"""
        generation_batch = self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        tasks = [
            TaskCenterService.build_task_list_item(task)
            for task in self.task_repository.list_tasks_by_generation_batch(generation_batch.id)
        ]
        return GenerationBatchDetailResponse(
            **self.build_generation_batch_list_item(generation_batch).model_dump(),
            lesson_plan_ids=self.repository.list_lesson_plan_ids_by_batch(generation_batch.id),
            tasks=tasks,
        )

    def _create_curriculum_task(
        self,
        *,
        generation_batch: GenerationBatch,
        owner_user_id: int,
        request: GenerationBatchCreateRequest,
        generation_run_id: int | None = None,
    ):
        """创建课程大纲生成任务。"""
        payload_json: dict[str, object] = {
            "generation_batch_id": generation_batch.id,
            "knowledge_version_id": request.knowledge_version_id,
            "learner_profile_version_id": request.learner_profile_version_id,
            "course_count": request.course_count,
            "session_duration_minutes": request.session_duration_minutes,
        }
        if generation_run_id is not None:
            payload_json["generation_run_id"] = generation_run_id
        task = self.task_repository.create_task(
            project_id=generation_batch.project_id,
            generation_batch_id=generation_batch.id,
            module_code=CURRICULUM_MODULE_CODE,
            task_type=CURRICULUM_GENERATE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=GENERATION_QUEUE_NAME,
            biz_key=f"generation_batch:{generation_batch.id}:curriculum",
            operator_user_id=owner_user_id,
            payload_json=payload_json,
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_generation_baseline", "准备生成基线"),
            ("invoke_llm_curriculum", "调用 LLM 生成课程大纲"),
            ("persist_curriculum_plan", "落库课程大纲"),
            ("finalize_generation_batch", "完成生成批次"),
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

    @staticmethod
    def build_generation_batch_list_item(generation_batch: GenerationBatch) -> GenerationBatchListItemResponse:
        """构造生成批次列表项响应。"""
        return GenerationBatchListItemResponse.model_validate(generation_batch, from_attributes=True)
