"""
@Date: 2026-04-30
@Author: xisy
@Discription: 调整语义块唯一键到知识版本维度
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260430_0004"
down_revision = "20260430_0003"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """判断索引是否存在。"""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    """将语义块序号唯一性限定到知识版本内。"""
    if _index_exists("semantic_chunk", "uk_semantic_chunk_parse_no"):
        op.drop_index("uk_semantic_chunk_parse_no", table_name="semantic_chunk")
    if not _index_exists("semantic_chunk", "uk_semantic_chunk_knowledge_no"):
        op.create_index(
            "uk_semantic_chunk_knowledge_no",
            "semantic_chunk",
            ["knowledge_version_id", "chunk_no"],
            unique=True,
        )


def downgrade() -> None:
    """恢复旧的解析版本维度唯一键。"""
    if _index_exists("semantic_chunk", "uk_semantic_chunk_knowledge_no"):
        op.drop_index("uk_semantic_chunk_knowledge_no", table_name="semantic_chunk")
    if not _index_exists("semantic_chunk", "uk_semantic_chunk_parse_no"):
        op.create_index(
            "uk_semantic_chunk_parse_no",
            "semantic_chunk",
            ["parse_version_id", "chunk_no"],
            unique=True,
        )
