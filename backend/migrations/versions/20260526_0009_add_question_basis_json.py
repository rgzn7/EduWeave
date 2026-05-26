"""
@Date: 2026-05-26
@Author: xisy
@Discription: 题目考查依据持久化：为 question_item / homework_question 新增 question_basis_json 列

upgrade：为两张题目表追加 JSON 列，存放装配好的题目考查依据。历史行为 NULL，由响应层兜底实时聚合。
downgrade：删除 question_basis_json 列。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260526_0009"
down_revision = "20260525_0008"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    """为 question_item / homework_question 新增 question_basis_json 列。"""
    if not _column_exists("question_item", "question_basis_json"):
        op.add_column(
            "question_item",
            sa.Column(
                "question_basis_json",
                mysql.JSON(),
                nullable=True,
                comment="题目考查依据",
            ),
        )
    if not _column_exists("homework_question", "question_basis_json"):
        op.add_column(
            "homework_question",
            sa.Column(
                "question_basis_json",
                mysql.JSON(),
                nullable=True,
                comment="题目考查依据",
            ),
        )


def downgrade() -> None:
    """回退：删除 question_basis_json 列。"""
    if _column_exists("homework_question", "question_basis_json"):
        op.drop_column("homework_question", "question_basis_json")
    if _column_exists("question_item", "question_basis_json"):
        op.drop_column("question_item", "question_basis_json")
