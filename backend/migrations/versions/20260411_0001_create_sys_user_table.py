"""
@Date: 2026-04-11
@Author: xisy
@Discription: 创建教师账号表
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260411_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sys_user",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("username", sa.String(length=64), nullable=False, comment="登录用户名"),
        sa.Column("display_name", sa.String(length=64), nullable=False, comment="显示名称"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码哈希"),
        sa.Column("role_code", sa.String(length=32), nullable=False, server_default=sa.text("'teacher'"), comment="角色编码"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'"), comment="状态：active/disabled"),
        sa.Column("last_login_at", mysql.DATETIME(fsp=3), nullable=True, comment="最近登录时间"),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            comment="更新时间",
        ),
        comment="系统用户表",
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("uk_sys_user_username", "sys_user", ["username"], unique=True)
    op.create_index("idx_sys_user_role_status", "sys_user", ["role_code", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_sys_user_role_status", table_name="sys_user")
    op.drop_index("uk_sys_user_username", table_name="sys_user")
    op.drop_table("sys_user")
