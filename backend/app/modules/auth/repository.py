"""
@Date: 2026-05-30
@Author: xisy
@Discription: 认证模块数据访问层
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import SysUser
from app.shared.utils.datetime_util import DateTimeUtil


class AuthRepository:
    """教师账号仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_username(self, username: str) -> SysUser | None:
        """按用户名查询教师账号。"""
        statement = select(SysUser).where(SysUser.username == username)
        return self.session.scalar(statement)

    def get_by_id(self, user_id: int) -> SysUser | None:
        """按主键查询教师账号。"""
        statement = select(SysUser).where(SysUser.id == user_id)
        return self.session.scalar(statement)

    def update_last_login(self, user: SysUser) -> None:
        """更新最近登录时间。"""
        user.last_login_at = DateTimeUtil.now_utc()
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)

    def save_user(self, user: SysUser) -> SysUser:
        """保存教师账号并刷新实体。"""
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user
