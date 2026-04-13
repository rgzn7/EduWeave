"""
@Date: 2026-04-11
@Author: xisy
@Discription: 教师账号模型定义
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MYSQL_BIGINT_UNSIGNED = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
MYSQL_DATETIME_MS = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


class SysUser(Base):
    """教师账号表。"""

    __tablename__ = "sys_user"
    __table_args__ = (
        Index("uk_sys_user_username", "username", unique=True),
        Index("idx_sys_user_role_status", "role_code", "status"),
        {"comment": "系统用户表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    username: Mapped[str] = mapped_column(String(64), nullable=False, comment="登录用户名")
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="显示名称")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    role_code: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="teacher",
        server_default=text("'teacher'"),
        comment="角色编码",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        comment="状态：active/disabled",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="最近登录时间")
    created_at: Mapped[datetime] = mapped_column(
        MYSQL_DATETIME_MS,
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        MYSQL_DATETIME_MS,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
