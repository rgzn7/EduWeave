"""
@Date: 2026-04-30
@Author: xisy
@Discription: 为章节与语义块补充 Markdown 行号范围
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260430_0005"
down_revision = "20260430_0004"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    """增加 Markdown 行号范围字段。"""
    if not _column_exists("chapter_node", "line_start"):
        op.add_column("chapter_node", sa.Column("line_start", sa.Integer(), nullable=True, comment="Markdown起始行号"))
    if not _column_exists("chapter_node", "line_end"):
        op.add_column("chapter_node", sa.Column("line_end", sa.Integer(), nullable=True, comment="Markdown结束行号"))
    if not _column_exists("semantic_chunk", "line_start"):
        op.add_column("semantic_chunk", sa.Column("line_start", sa.Integer(), nullable=True, comment="Markdown起始行号"))
    if not _column_exists("semantic_chunk", "line_end"):
        op.add_column("semantic_chunk", sa.Column("line_end", sa.Integer(), nullable=True, comment="Markdown结束行号"))


def downgrade() -> None:
    """移除 Markdown 行号范围字段。"""
    if _column_exists("semantic_chunk", "line_end"):
        op.drop_column("semantic_chunk", "line_end")
    if _column_exists("semantic_chunk", "line_start"):
        op.drop_column("semantic_chunk", "line_start")
    if _column_exists("chapter_node", "line_end"):
        op.drop_column("chapter_node", "line_end")
    if _column_exists("chapter_node", "line_start"):
        op.drop_column("chapter_node", "line_start")
