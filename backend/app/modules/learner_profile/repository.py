"""
@Date: 2026-04-13
@Author: xisy
@Discription: 学情模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import (
    FileObject,
    LearnerProfileFile,
    LearnerProfileRecord,
    LearnerProfileVersion,
    Project,
    TextbookVersion,
)


class LearnerProfileRepository:
    """学情模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_by_id_for_owner(self, project_id: int, owner_user_id: int) -> Project | None:
        """查询当前教师拥有的项目。"""
        statement = select(Project).where(Project.id == project_id, Project.owner_user_id == owner_user_id)
        return self.session.scalar(statement)

    def get_project(self, project_id: int) -> Project | None:
        """按主键查询项目。"""
        statement = select(Project).where(Project.id == project_id)
        return self.session.scalar(statement)

    def get_textbook_version_in_project(self, project_id: int, textbook_version_id: int) -> TextbookVersion | None:
        """查询项目下教材版本。"""
        statement = select(TextbookVersion).where(
            TextbookVersion.project_id == project_id,
            TextbookVersion.id == textbook_version_id,
        )
        return self.session.scalar(statement)

    def list_textbook_versions(self, project_id: int) -> list[TextbookVersion]:
        """查询项目下全部教材版本。"""
        statement = (
            select(TextbookVersion)
            .where(TextbookVersion.project_id == project_id)
            .order_by(TextbookVersion.created_at.desc(), TextbookVersion.id.desc())
        )
        return list(self.session.scalars(statement))

    def create_file_object(self, file_object: FileObject) -> FileObject:
        """创建文件对象。"""
        self.session.add(file_object)
        self.session.flush()
        return file_object

    def create_profile_file(self, profile_file: LearnerProfileFile) -> LearnerProfileFile:
        """创建学情文件。"""
        self.session.add(profile_file)
        self.session.flush()
        return profile_file

    def create_profile_version(self, profile_version: LearnerProfileVersion) -> LearnerProfileVersion:
        """创建学情版本。"""
        self.session.add(profile_version)
        self.session.flush()
        return profile_version

    def create_profile_record(self, profile_record: LearnerProfileRecord) -> LearnerProfileRecord:
        """创建学情画像记录。"""
        self.session.add(profile_record)
        self.session.flush()
        return profile_record

    def get_next_version_no(self, profile_file_id: int) -> int:
        """获取学情文件下一个版本号。"""
        statement = select(func.max(LearnerProfileVersion.version_no)).where(
            LearnerProfileVersion.profile_file_id == profile_file_id
        )
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def list_profile_files(self, project_id: int, offset: int, limit: int) -> list[LearnerProfileFile]:
        """分页查询学情文件。"""
        statement = (
            select(LearnerProfileFile)
            .where(LearnerProfileFile.project_id == project_id)
            .order_by(LearnerProfileFile.created_at.desc(), LearnerProfileFile.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_profile_files(self, project_id: int) -> int:
        """统计学情文件数量。"""
        statement = select(func.count()).select_from(LearnerProfileFile).where(LearnerProfileFile.project_id == project_id)
        return int(self.session.scalar(statement) or 0)

    def get_profile_file(self, project_id: int, profile_file_id: int) -> LearnerProfileFile | None:
        """查询项目下学情文件。"""
        statement = select(LearnerProfileFile).where(
            LearnerProfileFile.project_id == project_id,
            LearnerProfileFile.id == profile_file_id,
        )
        return self.session.scalar(statement)

    def get_profile_file_by_id(self, profile_file_id: int) -> LearnerProfileFile | None:
        """按主键查询学情文件。"""
        statement = select(LearnerProfileFile).where(LearnerProfileFile.id == profile_file_id)
        return self.session.scalar(statement)

    def get_latest_profile_version(self, profile_file_id: int) -> LearnerProfileVersion | None:
        """查询最新学情版本。"""
        statement = (
            select(LearnerProfileVersion)
            .where(LearnerProfileVersion.profile_file_id == profile_file_id)
            .order_by(LearnerProfileVersion.version_no.desc(), LearnerProfileVersion.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def list_profile_versions(self, profile_file_id: int, offset: int, limit: int) -> list[LearnerProfileVersion]:
        """分页查询学情版本列表。"""
        statement = (
            select(LearnerProfileVersion)
            .where(LearnerProfileVersion.profile_file_id == profile_file_id)
            .order_by(LearnerProfileVersion.version_no.desc(), LearnerProfileVersion.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_profile_versions(self, profile_file_id: int) -> int:
        """统计学情版本数量。"""
        statement = select(func.count()).select_from(LearnerProfileVersion).where(
            LearnerProfileVersion.profile_file_id == profile_file_id
        )
        return int(self.session.scalar(statement) or 0)

    def get_profile_version(self, profile_version_id: int) -> LearnerProfileVersion | None:
        """按主键查询学情版本。"""
        statement = select(LearnerProfileVersion).where(LearnerProfileVersion.id == profile_version_id)
        return self.session.scalar(statement)

    def get_profile_version_for_owner(self, profile_version_id: int, owner_user_id: int) -> LearnerProfileVersion | None:
        """查询当前教师可见的学情版本。"""
        statement = (
            select(LearnerProfileVersion)
            .join(Project, Project.id == LearnerProfileVersion.project_id)
            .where(LearnerProfileVersion.id == profile_version_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_profile_records(self, profile_version_id: int) -> list[LearnerProfileRecord]:
        """查询学情版本下画像记录。"""
        statement = (
            select(LearnerProfileRecord)
            .where(LearnerProfileRecord.profile_version_id == profile_version_id)
            .order_by(LearnerProfileRecord.sort_order.asc(), LearnerProfileRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_file_object(self, file_object_id: int) -> FileObject | None:
        """查询文件对象。"""
        statement = select(FileObject).where(FileObject.id == file_object_id)
        return self.session.scalar(statement)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
