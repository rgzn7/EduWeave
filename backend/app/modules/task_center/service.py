"""
@Date: 2026-04-13
@Author: xisy
@Discription: 任务中心模块业务服务
"""

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskDetailResponse, TaskListItemResponse, TaskStepResponse


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

    @staticmethod
    def build_task_list_item(task) -> TaskListItemResponse:
        """构造任务列表项响应。"""
        return TaskListItemResponse.model_validate(task, from_attributes=True)
