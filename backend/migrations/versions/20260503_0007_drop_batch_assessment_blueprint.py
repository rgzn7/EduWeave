"""
@Date: 2026-05-03
@Author: xisy
@Discription: 移除生成批次测评蓝图兼容字段
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260503_0007"
down_revision = "20260503_0006"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    """判断外键是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(foreign_key["name"] == constraint_name for foreign_key in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    """移除批次表上的单蓝图引用。"""
    if _foreign_key_exists("generation_batch", "fk_generation_batch_assessment_blueprint"):
        op.drop_constraint("fk_generation_batch_assessment_blueprint", "generation_batch", type_="foreignkey")
    if _column_exists("generation_batch", "assessment_blueprint_id"):
        op.drop_column("generation_batch", "assessment_blueprint_id")


def downgrade() -> None:
    """恢复批次表上的单蓝图引用。"""
    if not _column_exists("generation_batch", "assessment_blueprint_id"):
        op.add_column(
            "generation_batch",
            sa.Column("assessment_blueprint_id", mysql.BIGINT(unsigned=True), nullable=True, comment="生成的蓝图版本"),
        )
    if not _foreign_key_exists("generation_batch", "fk_generation_batch_assessment_blueprint"):
        op.create_foreign_key(
            "fk_generation_batch_assessment_blueprint",
            "generation_batch",
            "assessment_blueprint",
            ["assessment_blueprint_id"],
            ["id"],
        )
