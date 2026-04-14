"""
@Date: 2026-04-14
@Author: xisy
@Discription: 文件访问模块数据访问层
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.p0_models import FileObject, Project


class FileAssetRepository:
    """文件访问模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_file_object_for_owner(self, file_object_id: int, owner_user_id: int) -> FileObject | None:
        """按主键查询当前教师可见文件对象。"""
        statement = (
            select(FileObject)
            .join(Project, Project.id == FileObject.project_id)
            .where(FileObject.id == file_object_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)
