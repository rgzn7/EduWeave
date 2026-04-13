"""
@Date: 2026-04-13
@Author: xisy
@Discription: 教材模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import FileObject, Project, TextbookVersion


class TextbookRepository:
    """教材模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_by_id_for_owner(self, project_id: int, owner_user_id: int) -> Project | None:
        """查询当前教师拥有的项目。"""
        statement = select(Project).where(Project.id == project_id, Project.owner_user_id == owner_user_id)
        return self.session.scalar(statement)

    def get_next_version_no(self, project_id: int) -> int:
        """获取项目内下一个教材版本号。"""
        statement = select(func.max(TextbookVersion.version_no)).where(TextbookVersion.project_id == project_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_file_object(self, file_object: FileObject) -> FileObject:
        """创建文件对象。"""
        self.session.add(file_object)
        self.session.flush()
        return file_object

    def create_textbook_version(self, textbook_version: TextbookVersion) -> TextbookVersion:
        """创建教材版本。"""
        self.session.add(textbook_version)
        self.session.flush()
        return textbook_version

    def list_textbook_versions(self, project_id: int, offset: int, limit: int) -> list[TextbookVersion]:
        """分页查询教材版本。"""
        statement = (
            select(TextbookVersion)
            .where(TextbookVersion.project_id == project_id)
            .order_by(TextbookVersion.created_at.desc(), TextbookVersion.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_textbook_versions(self, project_id: int) -> int:
        """统计教材版本数量。"""
        statement = select(func.count()).select_from(TextbookVersion).where(TextbookVersion.project_id == project_id)
        return int(self.session.scalar(statement) or 0)

    def get_textbook_version(self, project_id: int, textbook_version_id: int) -> TextbookVersion | None:
        """查询项目下教材版本。"""
        statement = select(TextbookVersion).where(
            TextbookVersion.project_id == project_id,
            TextbookVersion.id == textbook_version_id,
        )
        return self.session.scalar(statement)

    def get_file_object(self, file_object_id: int) -> FileObject | None:
        """查询文件对象。"""
        statement = select(FileObject).where(FileObject.id == file_object_id)
        return self.session.scalar(statement)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
