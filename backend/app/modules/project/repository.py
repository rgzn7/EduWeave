"""
@Date: 2026-04-13
@Author: xisy
@Discription: 项目模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import LearnerProfileFile, LearnerProfileVersion, Project, TextbookVersion


class ProjectRepository:
    """项目模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_project(self, project: Project) -> Project:
        """创建项目。"""
        self.session.add(project)
        self.session.flush()
        return project

    def get_project_by_id_for_owner(self, project_id: int, owner_user_id: int) -> Project | None:
        """查询当前教师拥有的项目。"""
        statement = select(Project).where(Project.id == project_id, Project.owner_user_id == owner_user_id)
        return self.session.scalar(statement)

    def list_projects_for_owner(
        self,
        owner_user_id: int,
        *,
        status: str | None,
        subject_code: str | None,
        offset: int,
        limit: int,
    ) -> list[Project]:
        """分页列出当前教师项目。"""
        statement = select(Project).where(Project.owner_user_id == owner_user_id)
        if status:
            statement = statement.where(Project.status == status)
        if subject_code:
            statement = statement.where(Project.subject_code == subject_code)
        statement = statement.order_by(Project.updated_at.desc(), Project.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_projects_for_owner(self, owner_user_id: int, *, status: str | None, subject_code: str | None) -> int:
        """统计当前教师项目数。"""
        statement = select(func.count()).select_from(Project).where(Project.owner_user_id == owner_user_id)
        if status:
            statement = statement.where(Project.status == status)
        if subject_code:
            statement = statement.where(Project.subject_code == subject_code)
        return int(self.session.scalar(statement) or 0)

    def get_textbook_version_in_project(self, project_id: int, textbook_version_id: int) -> TextbookVersion | None:
        """查询项目下教材版本。"""
        statement = select(TextbookVersion).where(
            TextbookVersion.id == textbook_version_id,
            TextbookVersion.project_id == project_id,
        )
        return self.session.scalar(statement)

    def get_learner_profile_version_in_project(
        self, project_id: int, learner_profile_version_id: int
    ) -> LearnerProfileVersion | None:
        """查询项目下学情版本。"""
        statement = select(LearnerProfileVersion).where(
            LearnerProfileVersion.id == learner_profile_version_id,
            LearnerProfileVersion.project_id == project_id,
        )
        return self.session.scalar(statement)

    def get_current_textbook(self, current_textbook_version_id: int | None) -> TextbookVersion | None:
        """查询当前教材版本。"""
        if current_textbook_version_id is None:
            return None
        statement = select(TextbookVersion).where(TextbookVersion.id == current_textbook_version_id)
        return self.session.scalar(statement)

    def get_current_learner_profile(
        self, current_learner_profile_version_id: int | None
    ) -> LearnerProfileVersion | None:
        """查询当前学情版本。"""
        if current_learner_profile_version_id is None:
            return None
        statement = select(LearnerProfileVersion).where(
            LearnerProfileVersion.id == current_learner_profile_version_id
        )
        return self.session.scalar(statement)

    def count_textbooks(self, project_id: int) -> int:
        """统计项目教材数量。"""
        statement = select(func.count()).select_from(TextbookVersion).where(TextbookVersion.project_id == project_id)
        return int(self.session.scalar(statement) or 0)

    def count_learner_profile_files(self, project_id: int) -> int:
        """统计项目学情文件数量。"""
        statement = select(func.count()).select_from(LearnerProfileFile).where(LearnerProfileFile.project_id == project_id)
        return int(self.session.scalar(statement) or 0)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
