"""
@Date: 2026-05-28
@Author: xisy
@Discription: 任务中心模块业务服务
"""

from app.core.constants import (
    LESSON_PLAN_GENERATE_TASK_TYPE,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.p0_models import GenerationBatch, GenerationRun
from app.modules.task_center.heartbeat import dispatch_with_attempt
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.recovery import TASK_HANDLER_REGISTRY, build_dispatch_payload
from app.modules.task_center.schemas import TaskDetailResponse, TaskListItemResponse, TaskStepResponse
from app.shared.utils import DateTimeUtil


class TaskCenterService:
    """任务中心服务。"""

    def __init__(self, repository: TaskCenterRepository) -> None:
        self.repository = repository

    def list_tasks(
        self,
        *,
        owner_user_id: int,
        project_id: int | None,
        module_code: str | None,
        task_type: str | None,
        task_status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TaskListItemResponse], int]:
        """分页查询任务列表。"""
        offset = (page - 1) * page_size
        tasks = self.repository.list_tasks_for_owner(
            owner_user_id,
            project_id=project_id,
            module_code=module_code,
            task_type=task_type,
            task_status=task_status,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_tasks_for_owner(
            owner_user_id,
            project_id=project_id,
            module_code=module_code,
            task_type=task_type,
            task_status=task_status,
        )
        return [self.build_task_list_item(task) for task in tasks], total_count

    def get_task_detail(self, *, owner_user_id: int, task_id: int) -> TaskDetailResponse:
        """查询任务详情。"""
        task = self.repository.get_task_by_id_for_owner(task_id, owner_user_id)
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "任务不存在")
        steps = self.repository.list_task_steps(task.id)
        return TaskDetailResponse(
            **self.build_task_list_item(task).model_dump(),
            steps=[TaskStepResponse.model_validate(step, from_attributes=True) for step in steps],
        )

    def retry_task(self, *, owner_user_id: int, task_id: int) -> TaskDetailResponse:
        """手动重试失败的多课时教案生成任务。"""
        task = self.repository.get_task_by_id_for_owner(task_id, owner_user_id)
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.task_type != LESSON_PLAN_GENERATE_TASK_TYPE:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前仅支持重试教案生成任务")
        if task.task_status != TASK_STATUS_FAILURE:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "仅失败任务允许重试")
        callable_path = TASK_HANDLER_REGISTRY.get(task.task_type)
        if callable_path is None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "任务类型未注册处理器，无法重试")

        self._reset_task_for_retry(task)
        self._reset_related_generation_state(task)
        self.repository.session.commit()

        payload = build_dispatch_payload(task)
        try:
            dispatch_result = dispatch_with_attempt(
                self.repository,
                task=task,
                callable_path=callable_path,
                payload=payload,
                queue=task.queue_name,
            )
        except Exception as exc:  # noqa: BLE001
            self.repository.session.rollback()
            self._mark_retry_dispatch_failure(task, exc)
            self.repository.session.commit()
            raise AppException(BusinessErrorCode.EXTERNAL_SERVICE_ERROR, "任务重试派发失败，请稍后重试") from exc
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.repository.save(task)
            self.repository.session.commit()
        return self.get_task_detail(owner_user_id=owner_user_id, task_id=task_id)

    def _reset_task_for_retry(self, task) -> None:
        """清空失败任务状态并重置步骤，等待重新派发。"""
        task.task_status = TASK_STATUS_PENDING
        task.current_stage = None
        task.progress_percent = 0
        task.retry_count = 0
        task.worker_task_id = None
        task.result_json = None
        task.last_error_code = None
        task.last_error_message = None
        task.started_at = None
        task.finished_at = None
        task.last_heartbeat_at = None
        self.repository.save(task)
        for step in self.repository.list_task_steps(task.id):
            step.step_status = TASK_STATUS_PENDING
            step.progress_percent = 0
            step.detail_json = None
            step.started_at = None
            step.finished_at = None
            self.repository.save(step)

    def _reset_related_generation_state(self, task) -> None:
        """恢复生成批次和一键生成运行状态，保持原批次续跑。"""
        if task.generation_batch_id is not None:
            generation_batch = self.repository.session.get(GenerationBatch, task.generation_batch_id)
            if generation_batch is not None and generation_batch.batch_status == TASK_STATUS_FAILURE:
                generation_batch.batch_status = TASK_STATUS_PROCESSING
                generation_batch.finished_at = None
                self.repository.save(generation_batch)
        payload = task.payload_json or {}
        generation_run_id = payload.get("generation_run_id")
        if generation_run_id is None:
            return
        generation_run = self.repository.session.get(GenerationRun, int(generation_run_id))
        if generation_run is None or generation_run.run_status != "failed":
            return
        generation_run.run_status = "running"
        generation_run.last_error_code = None
        generation_run.last_error_message = None
        generation_run.blocked_reason = None
        generation_run.finished_at = None
        self.repository.save(generation_run)

    def _mark_retry_dispatch_failure(self, task, exc: Exception) -> None:
        """重试派发异常时恢复失败态，避免任务卡在 pending。"""
        now = DateTimeUtil.now_utc()
        message = "任务重试派发失败，请稍后重试"
        detail = str(exc)[:500]
        task.task_status = TASK_STATUS_FAILURE
        task.current_stage = None
        task.progress_percent = 0
        task.worker_task_id = None
        task.last_error_code = BusinessErrorCode.EXTERNAL_SERVICE_ERROR.value
        task.last_error_message = f"{message}：{detail}" if detail else message
        task.finished_at = now
        self.repository.save(task)
        steps = self.repository.list_task_steps(task.id)
        if steps:
            first_step = steps[0]
            first_step.step_status = TASK_STATUS_FAILURE
            first_step.progress_percent = 0
            first_step.detail_json = {
                "error_code": BusinessErrorCode.EXTERNAL_SERVICE_ERROR.value,
                "error_message": message,
            }
            first_step.finished_at = now
            self.repository.save(first_step)
        if task.generation_batch_id is not None:
            generation_batch = self.repository.session.get(GenerationBatch, task.generation_batch_id)
            if generation_batch is not None:
                generation_batch.batch_status = TASK_STATUS_FAILURE
                generation_batch.finished_at = now
                self.repository.save(generation_batch)
        payload = task.payload_json or {}
        generation_run_id = payload.get("generation_run_id")
        if generation_run_id is None:
            return
        generation_run = self.repository.session.get(GenerationRun, int(generation_run_id))
        if generation_run is None:
            return
        generation_run.run_status = "failed"
        generation_run.last_error_code = BusinessErrorCode.EXTERNAL_SERVICE_ERROR.value
        generation_run.last_error_message = message
        generation_run.finished_at = now
        self.repository.save(generation_run)

    @staticmethod
    def build_task_list_item(task) -> TaskListItemResponse:
        """构造任务列表项响应。"""
        return TaskListItemResponse.model_validate(task, from_attributes=True)
