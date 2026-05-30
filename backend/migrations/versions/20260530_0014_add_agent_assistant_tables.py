"""
@Date: 2026-05-30
@Author: xisy
@Discription: 新增项目级智能助手（EduWeave Agent）相关表迁移

upgrade：
- 新增 agent_session（会话）、agent_message（消息）、agent_run（运行）、
  agent_run_event（运行事件）、agent_artifact（运行工件）五张表
- 与 sql/20260529_agent_assistant_tables.sql 完全一致，含字段、索引、外键
downgrade：反序删除上述五张表。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260530_0014"
down_revision = "20260529_0013"
branch_labels = None
depends_on = None

# 建表顺序：依赖在前，被依赖者先建（drop 时反序）
_TABLES_IN_CREATE_ORDER = (
    "agent_session",
    "agent_message",
    "agent_run",
    "agent_run_event",
    "agent_artifact",
)

def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """新增智能助手五张表（按外键依赖顺序建表）。"""
    # 1. agent_session：会话表（被其余四表引用）
    if not _table_exists("agent_session"):
        op.create_table(
            "agent_session",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "user_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("sys_user.id", name="fk_agent_session_user"),
                nullable=False,
                comment="所属教师",
            ),
            sa.Column(
                "project_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("project.id", name="fk_agent_session_project"),
                nullable=True,
                comment="所属项目（项目级助手范围；单页全局会话可为空）",
            ),
            sa.Column("title", sa.String(length=255), nullable=True, comment="会话标题"),
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
            comment="智能助手会话表",
        )
        op.create_index("idx_agent_session_user", "agent_session", ["user_id", "updated_at"])
        op.create_index("idx_agent_session_project", "agent_session", ["project_id", "updated_at"])

    # 2. agent_message：消息表（依赖 agent_session）
    if not _table_exists("agent_message"):
        op.create_table(
            "agent_message",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "session_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("agent_session.id", name="fk_agent_message_session"),
                nullable=False,
                comment="所属会话",
            ),
            sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属教师"),
            sa.Column("run_id", mysql.BIGINT(unsigned=True), nullable=True, comment="产出该消息的运行"),
            sa.Column("role", sa.String(length=32), nullable=False, comment="消息角色：user/assistant"),
            sa.Column("content", mysql.MEDIUMTEXT(), nullable=True, comment="消息内容"),
            sa.Column("metadata_json", mysql.JSON(), nullable=True, comment="附加元数据"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                comment="创建时间",
            ),
            comment="智能助手消息表",
        )
        op.create_index("idx_agent_message_session", "agent_message", ["session_id", "id"])
        op.create_index("idx_agent_message_run", "agent_message", ["run_id"])

    # 3. agent_run：运行表（依赖 agent_session）
    if not _table_exists("agent_run"):
        op.create_table(
            "agent_run",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "session_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("agent_session.id", name="fk_agent_run_session"),
                nullable=False,
                comment="所属会话",
            ),
            sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=True, comment="所属项目"),
            sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属教师"),
            sa.Column("user_message_id", mysql.BIGINT(unsigned=True), nullable=True, comment="触发运行的用户消息"),
            sa.Column("assistant_message_id", mysql.BIGINT(unsigned=True), nullable=True, comment="运行成功落库的助手消息"),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending'"),
                comment="运行状态：pending/running/succeeded/failed/cancelled",
            ),
            sa.Column(
                "context_json",
                mysql.JSON(),
                nullable=True,
                comment="所在课次教案上下文：{project_id,curriculum_plan_id,class_session_no,lesson_plan_id}",
            ),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="已尝试次数"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3"), comment="最大尝试次数"),
            sa.Column("available_at", mysql.DATETIME(fsp=3), nullable=False, comment="可被抢占的时间"),
            sa.Column("locked_by", sa.String(length=64), nullable=False, server_default=sa.text("''"), comment="持锁 worker"),
            sa.Column("lease_expires_at", mysql.DATETIME(fsp=3), nullable=True, comment="租约过期时间"),
            sa.Column("last_error_code", sa.String(length=64), nullable=True, comment="最近错误码"),
            sa.Column("error_message", sa.Text(), nullable=True, comment="最近错误信息"),
            sa.Column("final_response", mysql.MEDIUMTEXT(), nullable=True, comment="最终回答文本"),
            sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True, comment="开始执行时间"),
            sa.Column("completed_at", mysql.DATETIME(fsp=3), nullable=True, comment="结束时间"),
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
            comment="智能助手运行表",
        )
        op.create_index("idx_agent_run_queue", "agent_run", ["status", "available_at"])
        op.create_index("idx_agent_run_session", "agent_run", ["session_id", "id"])

    # 4. agent_run_event：运行事件表（依赖 agent_run）
    if not _table_exists("agent_run_event"):
        op.create_table(
            "agent_run_event",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "run_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("agent_run.id", name="fk_agent_run_event_run"),
                nullable=False,
                comment="所属运行",
            ),
            sa.Column("session_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属会话"),
            sa.Column("seq", sa.Integer(), nullable=False, comment="运行内自增序号"),
            sa.Column("event_type", sa.String(length=32), nullable=False, comment="事件类型"),
            sa.Column("title", sa.String(length=255), nullable=True, comment="事件标题"),
            sa.Column("message", sa.Text(), nullable=True, comment="事件描述"),
            sa.Column("payload_json", mysql.JSON(), nullable=True, comment="事件载荷"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                comment="创建时间",
            ),
            comment="智能助手运行事件表",
        )
        op.create_index("uk_agent_run_event_seq", "agent_run_event", ["run_id", "seq"], unique=True)

    # 5. agent_artifact：运行工件表（依赖 agent_session）
    if not _table_exists("agent_artifact"):
        op.create_table(
            "agent_artifact",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column(
                "session_id",
                mysql.BIGINT(unsigned=True),
                sa.ForeignKey("agent_session.id", name="fk_agent_artifact_session"),
                nullable=False,
                comment="所属会话",
            ),
            sa.Column("source_tool", sa.String(length=64), nullable=False, comment="来源工具名"),
            sa.Column("content_hash", sa.String(length=64), nullable=False, comment="内容哈希（去重）"),
            sa.Column("title", sa.String(length=255), nullable=True, comment="工件标题"),
            sa.Column("summary", sa.Text(), nullable=True, comment="工件摘要预览"),
            sa.Column("content_text", mysql.MEDIUMTEXT(), nullable=False, comment="工件全文"),
            sa.Column("superseded_at", mysql.DATETIME(fsp=3), nullable=True, comment="失效时间"),
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
            comment="智能助手运行工件表",
        )
        op.create_index(
            "uk_agent_artifact_hash",
            "agent_artifact",
            ["session_id", "source_tool", "content_hash"],
            unique=True,
        )
        op.create_index("idx_agent_artifact_session", "agent_artifact", ["session_id", "id"])


def downgrade() -> None:
    """回退：按外键依赖反序删除五张表。"""
    for table_name in reversed(_TABLES_IN_CREATE_ORDER):
        if _table_exists(table_name):
            op.drop_table(table_name)




