"""
@Date: 2026-05-27
@Author: xisy
@Discription: 任务中心模块数据访问层
"""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.constants import TASK_STATUS_FAILURE, TASK_STATUS_PROCESSING
from app.modules.p0_models import Project, TaskRecord, TaskStepRecord


class TaskCenterRepository:
    """任务中心仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_task(
        self,
        *,
        project_id: int,
        module_code: str,
        task_type: str,
        task_status: str,
        queue_name: str | None,
        biz_key: str | None,
        operator_user_id: int | None,
        payload_json: dict[str, Any] | None,
        request_id: str | None,
        generation_batch_id: int | None = None,
        current_stage: str | None = None,
        progress_percent: int = 0,
        retry_count: int = 0,
        max_retry_count: int = 3,
        worker_task_id: str | None = None,
        result_json: dict[str, Any] | None = None,
        last_error_code: str | None = None,
        last_error_message: str | None = None,
        started_at=None,
        finished_at=None,
    ) -> TaskRecord:
        """创建任务主记录。"""
        task = TaskRecord(
            project_id=project_id,
            generation_batch_id=generation_batch_id,
            module_code=module_code,
            task_type=task_type,
            biz_key=biz_key,
            task_status=task_status,
            queue_name=queue_name,
            current_stage=current_stage,
            progress_percent=progress_percent,
            retry_count=retry_count,
            max_retry_count=max_retry_count,
            request_id=request_id,
            worker_task_id=worker_task_id,
            operator_user_id=operator_user_id,
            payload_json=payload_json,
            result_json=result_json,
            last_error_code=last_error_code,
            last_error_message=last_error_message,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def create_task_step(
        self,
        *,
        task_record_id: int,
        step_code: str,
        step_name: str,
        step_order: int,
        step_status: str,
        progress_percent: int = 0,
        detail_json: dict[str, Any] | None = None,
        started_at=None,
        finished_at=None,
    ) -> TaskStepRecord:
        """创建任务步骤记录。"""
        step = TaskStepRecord(
            task_record_id=task_record_id,
            step_code=step_code,
            step_name=step_name,
            step_order=step_order,
            step_status=step_status,
            progress_percent=progress_percent,
            detail_json=detail_json,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.session.add(step)
        self.session.flush()
        return step

    def get_task_by_id_for_owner(self, task_id: int, owner_user_id: int) -> TaskRecord | None:
        """按主键查询当前教师可见任务。"""
        statement = (
            select(TaskRecord)
            .join(Project, Project.id == TaskRecord.project_id)
            .where(TaskRecord.id == task_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_task_steps(self, task_record_id: int) -> list[TaskStepRecord]:
        """列出任务步骤。"""
        statement = (
            select(TaskStepRecord)
            .where(TaskStepRecord.task_record_id == task_record_id)
            .order_by(TaskStepRecord.step_order.asc(), TaskStepRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_tasks_for_owner(
        self,
        owner_user_id: int,
        *,
        project_id: int | None,
        module_code: str | None,
        task_type: str | None,
        task_status: str | None,
        offset: int,
        limit: int,
    ) -> list[TaskRecord]:
        """按条件分页列出任务。"""
        statement = self._build_owner_task_statement(
            owner_user_id=owner_user_id,
            project_id=project_id,
            module_code=module_code,
            task_type=task_type,
            task_status=task_status,
        )
        statement = statement.order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_tasks_for_owner(
        self,
        owner_user_id: int,
        *,
        project_id: int | None,
        module_code: str | None,
        task_type: str | None,
        task_status: str | None,
    ) -> int:
        """统计当前教师可见任务总数。"""
        statement = self._build_owner_task_statement(
            owner_user_id=owner_user_id,
            project_id=project_id,
            module_code=module_code,
            task_type=task_type,
            task_status=task_status,
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        return int(self.session.scalar(count_statement) or 0)

    def list_recent_tasks(self, project_id: int, limit: int = 5) -> list[TaskRecord]:
        """查询项目最近任务。"""
        statement = (
            select(TaskRecord)
            .where(TaskRecord.project_id == project_id)
            .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_tasks_by_generation_batch(self, generation_batch_id: int) -> list[TaskRecord]:
        """查询生成批次关联任务。"""
        statement = (
            select(TaskRecord)
            .where(TaskRecord.generation_batch_id == generation_batch_id)
            .order_by(TaskRecord.created_at.asc(), TaskRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def count_project_tasks(self, project_id: int) -> int:
        """统计项目任务总数。"""
        statement = select(func.count()).select_from(TaskRecord).where(TaskRecord.project_id == project_id)
        return int(self.session.scalar(statement) or 0)

    def count_project_processing_tasks(self, project_id: int) -> int:
        """统计处理中任务数。"""
        statement = (
            select(func.count())
            .select_from(TaskRecord)
            .where(TaskRecord.project_id == project_id, TaskRecord.task_status == TASK_STATUS_PROCESSING)
        )
        return int(self.session.scalar(statement) or 0)

    def count_project_failure_tasks(self, project_id: int) -> int:
        """统计失败任务数。"""
        statement = (
            select(func.count())
            .select_from(TaskRecord)
            .where(TaskRecord.project_id == project_id, TaskRecord.task_status == TASK_STATUS_FAILURE)
        )
        return int(self.session.scalar(statement) or 0)

    def count_project_tasks_by_type(self, project_id: int, task_type: str) -> int:
        """统计项目指定任务类型数量。"""
        statement = (
            select(func.count())
            .select_from(TaskRecord)
            .where(TaskRecord.project_id == project_id, TaskRecord.task_type == task_type)
        )
        return int(self.session.scalar(statement) or 0)

    def get_active_task_by_biz_key(self, *, module_code: str, task_type: str, biz_key: str) -> TaskRecord | None:
        """查询同业务键下的运行中任务。"""
        statement = select(TaskRecord).where(
            TaskRecord.module_code == module_code,
            TaskRecord.task_type == task_type,
            TaskRecord.biz_key == biz_key,
            TaskRecord.task_status.in_(["pending", "processing"]),
        )
        return self.session.scalar(statement)

    def get_latest_task_by_biz_key(
        self,
        *,
        module_code: str,
        task_type: str,
        biz_key: str,
    ) -> TaskRecord | None:
        """查询业务键下最近一条任务（不区分状态）。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.module_code == module_code,
                TaskRecord.task_type == task_type,
                TaskRecord.biz_key == biz_key,
            )
            .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_latest_task_by_project_and_type(
        self,
        *,
        project_id: int,
        module_code: str,
        task_type: str,
    ) -> TaskRecord | None:
        """查询项目下指定任务类型的最近一条任务（不区分状态）。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.project_id == project_id,
                TaskRecord.module_code == module_code,
                TaskRecord.task_type == task_type,
            )
            .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_task_by_id(self, task_id: int) -> TaskRecord | None:
        """按主键查询任务。"""
        statement = select(TaskRecord).where(TaskRecord.id == task_id)
        return self.session.scalar(statement)

    def get_task_step(self, task_record_id: int, step_code: str) -> TaskStepRecord | None:
        """按任务和步骤编码查询步骤。"""
        statement = select(TaskStepRecord).where(
            TaskStepRecord.task_record_id == task_record_id,
            TaskStepRecord.step_code == step_code,
        )
        return self.session.scalar(statement)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()

    def _build_owner_task_statement(
        self,
        *,
        owner_user_id: int,
        project_id: int | None,
        module_code: str | None,
        task_type: str | None,
        task_status: str | None,
    ) -> Select[tuple[TaskRecord]]:
        statement = select(TaskRecord).join(Project, Project.id == TaskRecord.project_id).where(
            Project.owner_user_id == owner_user_id
        )
        if project_id is not None:
            statement = statement.where(TaskRecord.project_id == project_id)
        if module_code:
            statement = statement.where(TaskRecord.module_code == module_code)
        if task_type:
            statement = statement.where(TaskRecord.task_type == task_type)
        if task_status:
            statement = statement.where(TaskRecord.task_status == task_status)
        return statement
