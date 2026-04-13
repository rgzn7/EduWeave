"""
@Date: 2026-04-13
@Author: xisy
@Discription: 项目模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import TEXTBOOK_PARSE_TASK_TYPE
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.p0_models import Project
from app.modules.project.repository import ProjectRepository
from app.modules.project.schemas import (
    ProjectCreateRequest,
    ProjectCurrentLearnerProfileResponse,
    ProjectCurrentTextbookResponse,
    ProjectDashboardResponse,
    ProjectDashboardStatsResponse,
    ProjectDetailResponse,
    ProjectListItemResponse,
)
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.service import TaskCenterService
from app.shared.utils.datetime_util import DateTimeUtil


class ProjectService:
    """项目模块服务。"""

    def __init__(self, session: Session, repository: ProjectRepository | None = None) -> None:
        self.session = session
        self.repository = repository or ProjectRepository(session)
        self.task_repository = TaskCenterRepository(session)

    def create_project(self, owner_user_id: int, request: ProjectCreateRequest) -> ProjectDetailResponse:
        """创建项目。"""
        project = Project(
            owner_user_id=owner_user_id,
            project_code=request.project_code,
            name=request.name,
            subject_code=request.subject_code,
            grade_code=request.grade_code,
            applicable_target=request.applicable_target,
            remark=request.remark,
            status="active",
            last_activity_at=DateTimeUtil.now_utc(),
        )
        self.repository.create_project(project)
        self.session.commit()
        self.session.refresh(project)
        return self.build_project_detail(project)

    def list_projects(
        self,
        owner_user_id: int,
        *,
        status: str | None,
        subject_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ProjectListItemResponse], int]:
        """分页查询项目列表。"""
        offset = (page - 1) * page_size
        projects = self.repository.list_projects_for_owner(
            owner_user_id,
            status=status,
            subject_code=subject_code,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_projects_for_owner(
            owner_user_id,
            status=status,
            subject_code=subject_code,
        )
        return [ProjectListItemResponse.model_validate(project, from_attributes=True) for project in projects], total_count

    def get_project_detail(self, owner_user_id: int, project_id: int) -> ProjectDetailResponse:
        """查询项目详情。"""
        project = self.get_owned_project(owner_user_id, project_id)
        return self.build_project_detail(project)

    def get_project_dashboard(self, owner_user_id: int, project_id: int) -> ProjectDashboardResponse:
        """查询项目工作台数据。"""
        project = self.get_owned_project(owner_user_id, project_id)
        stats = ProjectDashboardStatsResponse(
            textbook_count=self.repository.count_textbooks(project.id),
            learner_profile_file_count=self.repository.count_learner_profile_files(project.id),
            task_total_count=self.task_repository.count_project_tasks(project.id),
            parsing_task_count=self.task_repository.count_project_tasks_by_type(project.id, TEXTBOOK_PARSE_TASK_TYPE),
            processing_task_count=self.task_repository.count_project_processing_tasks(project.id),
            failure_task_count=self.task_repository.count_project_failure_tasks(project.id),
        )
        recent_tasks = [
            TaskCenterService.build_task_list_item(task)
            for task in self.task_repository.list_recent_tasks(project.id)
        ]
        return ProjectDashboardResponse(
            project=self.build_project_detail(project),
            stats=stats,
            recent_tasks=recent_tasks,
        )

    def update_active_refs(
        self,
        owner_user_id: int,
        project_id: int,
        *,
        current_textbook_version_id: int | None,
        current_learner_profile_version_id: int | None,
    ) -> ProjectDetailResponse:
        """更新项目当前引用。"""
        project = self.get_owned_project(owner_user_id, project_id)
        if current_textbook_version_id is not None:
            textbook = self.repository.get_textbook_version_in_project(project.id, current_textbook_version_id)
            if textbook is None:
                raise AppException(BusinessErrorCode.PROJECT_REFERENCE_INVALID, "教材版本不属于当前项目")
            project.current_textbook_version_id = textbook.id
        if current_learner_profile_version_id is not None:
            profile_version = self.repository.get_learner_profile_version_in_project(
                project.id,
                current_learner_profile_version_id,
            )
            if profile_version is None:
                raise AppException(BusinessErrorCode.PROJECT_REFERENCE_INVALID, "学情版本不属于当前项目")
            project.current_learner_profile_version_id = profile_version.id
        project.last_activity_at = DateTimeUtil.now_utc()
        self.repository.save(project)
        self.session.commit()
        self.session.refresh(project)
        return self.build_project_detail(project)

    def get_owned_project(self, owner_user_id: int, project_id: int) -> Project:
        """获取当前教师拥有的项目。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        return project

    def build_project_detail(self, project: Project) -> ProjectDetailResponse:
        """构造项目详情响应。"""
        current_textbook = self.repository.get_current_textbook(project.current_textbook_version_id)
        current_profile = self.repository.get_current_learner_profile(project.current_learner_profile_version_id)
        return ProjectDetailResponse(
            **ProjectListItemResponse.model_validate(project, from_attributes=True).model_dump(),
            owner_user_id=project.owner_user_id,
            current_textbook=(
                ProjectCurrentTextbookResponse.model_validate(current_textbook, from_attributes=True)
                if current_textbook is not None
                else None
            ),
            current_learner_profile=(
                ProjectCurrentLearnerProfileResponse.model_validate(current_profile, from_attributes=True)
                if current_profile is not None
                else None
            ),
        )
