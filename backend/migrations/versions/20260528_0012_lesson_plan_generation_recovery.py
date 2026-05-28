"""
@Date: 2026-05-28
@Author: xisy
@Discription: 多课时教案课次级生成恢复迁移

upgrade：
- 新增 lesson_plan_generation_item 表，保存每课次生成中间结果、LLM 用量和失败详情
downgrade：删除 lesson_plan_generation_item 表。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260528_0012"
down_revision = "20260527_0011"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """新增教案课次生成中间结果表。"""
    if _table_exists("lesson_plan_generation_item"):
        return
    op.create_table(
        "lesson_plan_generation_item",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column(
            "generation_batch_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("generation_batch.id", name="fk_lesson_plan_generation_item_batch"),
            nullable=False,
            comment="生成批次",
        ),
        sa.Column(
            "task_record_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("task_record.id", name="fk_lesson_plan_generation_item_task"),
            nullable=True,
            comment="任务主表",
        ),
        sa.Column("class_session_no", sa.Integer(), nullable=False, comment="课次序号"),
        sa.Column("lesson_title", sa.String(length=255), nullable=True, comment="课次标题"),
        sa.Column(
            "item_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="课次生成状态：pending/processing/success/failure",
        ),
        sa.Column("summary_text", sa.Text(), nullable=True, comment="摘要"),
        sa.Column("content_json", mysql.JSON(), nullable=True, comment="教案内容"),
        sa.Column("llm_usage_json", mysql.JSON(), nullable=True, comment="LLM 用量"),
        sa.Column("last_error_code", sa.String(length=64), nullable=True, comment="错误码"),
        sa.Column("last_error_message", sa.String(length=500), nullable=True, comment="错误信息"),
        sa.Column("last_error_detail_json", mysql.JSON(), nullable=True, comment="错误详情"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="重试次数"),
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
        comment="教案课次生成中间结果表",
    )
    op.create_index(
        "uk_lesson_plan_generation_item_session",
        "lesson_plan_generation_item",
        ["generation_batch_id", "class_session_no"],
        unique=True,
    )
    op.create_index(
        "idx_lesson_plan_generation_item_task",
        "lesson_plan_generation_item",
        ["task_record_id", "item_status"],
    )
    op.create_index(
        "idx_lesson_plan_generation_item_batch_status",
        "lesson_plan_generation_item",
        ["generation_batch_id", "item_status"],
    )


def downgrade() -> None:
    """删除教案课次生成中间结果表。"""
    if not _table_exists("lesson_plan_generation_item"):
        return
    op.drop_index("idx_lesson_plan_generation_item_batch_status", table_name="lesson_plan_generation_item")
    op.drop_index("idx_lesson_plan_generation_item_task", table_name="lesson_plan_generation_item")
    op.drop_index("uk_lesson_plan_generation_item_session", table_name="lesson_plan_generation_item")
    op.drop_table("lesson_plan_generation_item")
