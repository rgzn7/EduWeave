"""
@Date: 2026-05-26
@Author: xisy
@Discription: Phase2 一键生成编排基础设施迁移

upgrade：
- 为 task_record 增加 last_heartbeat_at（心跳）与 execution_attempt_id（执行实例 ID）两列
- 新增 generation_run 表，承载后端全权编排的一次生成运行
- 为 project 增加 active_generation_run_id 外键，做单 project 单活跃 run 的幂等锚点
downgrade：反向删除上述新增对象。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260526_0010"
down_revision = "20260526_0009"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """新增 generation_run 表、task_record 心跳列、project 活跃 run 外键。"""
    # task_record 新增心跳与执行实例 ID
    if not _column_exists("task_record", "last_heartbeat_at"):
        op.add_column(
            "task_record",
            sa.Column(
                "last_heartbeat_at",
                mysql.DATETIME(fsp=3),
                nullable=True,
                comment="最近心跳时间",
            ),
        )
    if not _column_exists("task_record", "execution_attempt_id"):
        op.add_column(
            "task_record",
            sa.Column(
                "execution_attempt_id",
                sa.String(length=36),
                nullable=True,
                comment="本次执行实例ID",
            ),
        )

    # generation_run 主表
    if not _table_exists("generation_run"):
        op.create_table(
            "generation_run",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "project_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("project.id", name="fk_generation_run_project"),
                nullable=False,
                comment="所属项目",
            ),
            sa.Column(
                "run_status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending'"),
                comment="运行状态：pending/running/waiting_user_confirm/succeeded/failed/cancelled",
            ),
            sa.Column("course_count", sa.Integer(), nullable=False, comment="课次数"),
            sa.Column("session_duration_minutes", sa.Integer(), nullable=False, comment="单次时长"),
            sa.Column("chapter_range_json", mysql.JSON(), nullable=True, comment="章节范围"),
            sa.Column(
                "auto_confirm_parse",
                mysql.TINYINT(display_width=1),
                nullable=False,
                server_default=sa.text("1"),
                comment="解析自动确认开关",
            ),
            sa.Column(
                "parse_version_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("parse_version.id", name="fk_generation_run_parse_version"),
                nullable=True,
                comment="本次运行使用的解析版本",
            ),
            sa.Column(
                "knowledge_version_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("knowledge_version.id", name="fk_generation_run_knowledge_version"),
                nullable=True,
                comment="本次运行使用的知识版本",
            ),
            sa.Column(
                "generation_batch_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("generation_batch.id", name="fk_generation_run_generation_batch"),
                nullable=True,
                comment="本次运行创建的生成批次",
            ),
            sa.Column("last_error_code", sa.String(length=64), nullable=True, comment="错误码"),
            sa.Column("last_error_message", sa.String(length=500), nullable=True, comment="错误信息"),
            sa.Column("blocked_reason", sa.String(length=64), nullable=True, comment="阻塞原因编码"),
            sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True, comment="开始时间"),
            sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True, comment="结束时间"),
            sa.Column(
                "created_by",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("sys_user.id", name="fk_generation_run_created_by"),
                nullable=True,
                comment="创建人",
            ),
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
            comment="一键生成运行表",
        )
        op.create_index(
            "idx_generation_run_project_status",
            "generation_run",
            ["project_id", "run_status", "created_at"],
        )

    # project 增加 active_generation_run_id；FK 必须在 generation_run 已存在时再加
    if not _column_exists("project", "active_generation_run_id"):
        op.add_column(
            "project",
            sa.Column(
                "active_generation_run_id",
                mysql.BIGINT(unsigned=True),
                nullable=True,
                comment="当前活跃一键生成运行",
            ),
        )
        op.create_foreign_key(
            "fk_project_active_generation_run",
            "project",
            "generation_run",
            ["active_generation_run_id"],
            ["id"],
        )


def downgrade() -> None:
    """回退：删除外键、列与表。"""
    if _column_exists("project", "active_generation_run_id"):
        try:
            op.drop_constraint("fk_project_active_generation_run", "project", type_="foreignkey")
        except Exception:  # noqa: BLE001
            # 测试库可能为 SQLite 等无 FK 实例，忽略
            pass
        op.drop_column("project", "active_generation_run_id")

    if _table_exists("generation_run"):
        try:
            op.drop_index("idx_generation_run_project_status", table_name="generation_run")
        except Exception:  # noqa: BLE001
            pass
        op.drop_table("generation_run")

    if _column_exists("task_record", "execution_attempt_id"):
        op.drop_column("task_record", "execution_attempt_id")
    if _column_exists("task_record", "last_heartbeat_at"):
        op.drop_column("task_record", "last_heartbeat_at")
