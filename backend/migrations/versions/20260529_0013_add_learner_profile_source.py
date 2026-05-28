"""
@Date: 2026-05-29
@Author: xisy
@Discription: 新增学情班级源文件表迁移

upgrade：
- 新增 learner_profile_source 表，支持一个班级（learner_profile_file）挂多个学生 docx
downgrade：删除 learner_profile_source 表。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260529_0013"
down_revision = "20260528_0012"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """新增学情班级源文件表。"""
    if _table_exists("learner_profile_source"):
        return
    op.create_table(
        "learner_profile_source",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column(
            "project_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("project.id", name="fk_profile_source_project"),
            nullable=False,
            comment="所属项目",
        ),
        sa.Column(
            "profile_file_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("learner_profile_file.id", name="fk_profile_source_file"),
            nullable=False,
            comment="学情文件（班级）",
        ),
        sa.Column(
            "file_object_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("file_object.id", name="fk_profile_source_file_object"),
            nullable=False,
            comment="学生源 docx 文件对象",
        ),
        sa.Column("student_seq", sa.Integer(), nullable=False, comment="班级内学生序号（从 1 递增）"),
        sa.Column("original_filename", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column("student_name", sa.String(length=128), nullable=True, comment="学生姓名（解析后回填）"),
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
        comment="学情班级源文件表",
    )
    op.create_index(
        "uk_profile_source_file_seq",
        "learner_profile_source",
        ["profile_file_id", "student_seq"],
        unique=True,
    )
    op.create_index(
        "idx_profile_source_file",
        "learner_profile_source",
        ["profile_file_id"],
    )


def downgrade() -> None:
    """删除学情班级源文件表。"""
    if not _table_exists("learner_profile_source"):
        return
    op.drop_index("idx_profile_source_file", table_name="learner_profile_source")
    op.drop_index("uk_profile_source_file_seq", table_name="learner_profile_source")
    op.drop_table("learner_profile_source")
