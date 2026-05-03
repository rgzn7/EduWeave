"""
@Date: 2026-05-03
@Author: xisy
@Discription: 拆分生成链路并补齐教案批次血缘
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260503_0006"
down_revision = "20260430_0005"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    """判断索引是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    """判断外键是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(foreign_key["name"] == constraint_name for foreign_key in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    """增加教案批次血缘并调整课件唯一约束。"""
    if not _column_exists("lesson_plan", "generation_batch_id"):
        op.add_column(
            "lesson_plan",
            sa.Column("generation_batch_id", mysql.BIGINT(unsigned=True), nullable=True, comment="生成批次"),
        )
    if not _column_exists("lesson_plan", "class_session_no"):
        op.add_column("lesson_plan", sa.Column("class_session_no", sa.Integer(), nullable=True, comment="课次序号"))

    op.execute(
        """
        UPDATE lesson_plan AS lp
        JOIN generation_batch AS gb ON gb.lesson_plan_id = lp.id
        SET lp.generation_batch_id = gb.id,
            lp.class_session_no = COALESCE(lp.class_session_no, 1)
        WHERE lp.generation_batch_id IS NULL
        """
    )

    if not _index_exists("lesson_plan", "uk_lesson_plan_batch_session"):
        op.create_index(
            "uk_lesson_plan_batch_session",
            "lesson_plan",
            ["generation_batch_id", "class_session_no"],
            unique=True,
        )
    if not _index_exists("lesson_plan", "idx_lesson_plan_generation_batch"):
        op.create_index(
            "idx_lesson_plan_generation_batch",
            "lesson_plan",
            ["generation_batch_id", "class_session_no"],
            unique=False,
        )
    if not _foreign_key_exists("lesson_plan", "fk_lesson_plan_generation_batch"):
        op.create_foreign_key(
            "fk_lesson_plan_generation_batch",
            "lesson_plan",
            "generation_batch",
            ["generation_batch_id"],
            ["id"],
        )

    if not _index_exists("courseware_result", "uk_courseware_result_batch_lesson"):
        op.create_index(
            "uk_courseware_result_batch_lesson",
            "courseware_result",
            ["generation_batch_id", "lesson_plan_id"],
            unique=True,
        )
    if _index_exists("courseware_result", "uk_courseware_result_batch"):
        op.drop_index("uk_courseware_result_batch", table_name="courseware_result")


def downgrade() -> None:
    """回退教案批次血缘与课件唯一约束。"""
    if not _index_exists("courseware_result", "uk_courseware_result_batch"):
        op.create_index("uk_courseware_result_batch", "courseware_result", ["generation_batch_id"], unique=True)
    if _index_exists("courseware_result", "uk_courseware_result_batch_lesson"):
        op.drop_index("uk_courseware_result_batch_lesson", table_name="courseware_result")

    if _foreign_key_exists("lesson_plan", "fk_lesson_plan_generation_batch"):
        op.drop_constraint("fk_lesson_plan_generation_batch", "lesson_plan", type_="foreignkey")
    if _index_exists("lesson_plan", "idx_lesson_plan_generation_batch"):
        op.drop_index("idx_lesson_plan_generation_batch", table_name="lesson_plan")
    if _index_exists("lesson_plan", "uk_lesson_plan_batch_session"):
        op.drop_index("uk_lesson_plan_batch_session", table_name="lesson_plan")
    if _column_exists("lesson_plan", "class_session_no"):
        op.drop_column("lesson_plan", "class_session_no")
    if _column_exists("lesson_plan", "generation_batch_id"):
        op.drop_column("lesson_plan", "generation_batch_id")
