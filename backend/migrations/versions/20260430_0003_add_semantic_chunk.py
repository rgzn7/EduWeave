"""
@Date: 2026-04-30
@Author: xisy
@Discription: 新增教材语义块表并关联知识证据
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260430_0003"
down_revision = "20260413_0002"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """判断列是否存在。"""
    if not _table_exists(table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    """判断索引是否存在。"""
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def _foreign_key_exists(table_name: str, foreign_key_name: str) -> bool:
    """判断外键是否存在。"""
    if not _table_exists(table_name):
        return False
    return any(foreign_key["name"] == foreign_key_name for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name))


def upgrade() -> None:
    """补齐语义块 schema，兼容已执行旧 27 表迁移的本地库。"""
    if not _table_exists("semantic_chunk"):
        op.create_table(
            "semantic_chunk",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属项目"),
            sa.Column("parse_version_id", mysql.BIGINT(unsigned=True), nullable=False, comment="解析版本"),
            sa.Column("knowledge_version_id", mysql.BIGINT(unsigned=True), nullable=True, comment="知识版本"),
            sa.Column("chapter_node_id", mysql.BIGINT(unsigned=True), nullable=True, comment="章节节点"),
            sa.Column("chunk_no", sa.Integer(), nullable=False, comment="语义块序号"),
            sa.Column("chunk_title", sa.String(length=255), nullable=True, comment="语义块标题"),
            sa.Column(
                "chunk_type",
                sa.String(length=32),
                server_default=sa.text("'semantic'"),
                nullable=False,
                comment="语义块类型",
            ),
            sa.Column("page_start", sa.Integer(), nullable=True, comment="起始页"),
            sa.Column("page_end", sa.Integer(), nullable=True, comment="结束页"),
            sa.Column("line_start", sa.Integer(), nullable=True, comment="Markdown起始行号"),
            sa.Column("line_end", sa.Integer(), nullable=True, comment="Markdown结束行号"),
            sa.Column(
                "source_block_refs_json",
                mysql.JSON(),
                nullable=True,
                comment="来源解析块引用，保留页码、块号、坐标和资源文件",
            ),
            sa.Column("source_text_hash", sa.String(length=128), nullable=True, comment="来源文本哈希"),
            sa.Column("chunk_text", mysql.MEDIUMTEXT(), nullable=False, comment="语义块正文"),
            sa.Column("summary_text", sa.Text(), nullable=True, comment="摘要"),
            sa.Column("metadata_json", mysql.JSON(), nullable=True, comment="附加元数据"),
            sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=True, comment="创建人"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="创建时间",
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="更新时间",
            ),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_comment="教材语义块表",
        )
        op.create_index("uk_semantic_chunk_knowledge_no", "semantic_chunk", ["knowledge_version_id", "chunk_no"], unique=True)
        op.create_index("idx_semantic_chunk_project", "semantic_chunk", ["project_id", "created_at"])
        op.create_index("idx_semantic_chunk_knowledge", "semantic_chunk", ["knowledge_version_id", "chapter_node_id"])
        op.create_index(
            "idx_semantic_chunk_page_range",
            "semantic_chunk",
            ["parse_version_id", "page_start", "page_end"],
        )
        op.create_foreign_key("fk_semantic_chunk_project", "semantic_chunk", "project", ["project_id"], ["id"])
        op.create_foreign_key(
            "fk_semantic_chunk_parse_version",
            "semantic_chunk",
            "parse_version",
            ["parse_version_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_semantic_chunk_knowledge_version",
            "semantic_chunk",
            "knowledge_version",
            ["knowledge_version_id"],
            ["id"],
        )
        op.create_foreign_key("fk_semantic_chunk_chapter", "semantic_chunk", "chapter_node", ["chapter_node_id"], ["id"])
        op.create_foreign_key("fk_semantic_chunk_created_by", "semantic_chunk", "sys_user", ["created_by"], ["id"])

    if _table_exists("knowledge_evidence") and not _column_exists("knowledge_evidence", "semantic_chunk_id"):
        op.add_column(
            "knowledge_evidence",
            sa.Column("semantic_chunk_id", mysql.BIGINT(unsigned=True), nullable=True, comment="语义块"),
        )
    if _table_exists("knowledge_evidence") and not _index_exists(
        "knowledge_evidence",
        "idx_knowledge_evidence_semantic_chunk",
    ):
        op.create_index("idx_knowledge_evidence_semantic_chunk", "knowledge_evidence", ["semantic_chunk_id"])
    if _table_exists("knowledge_evidence") and not _foreign_key_exists(
        "knowledge_evidence",
        "fk_knowledge_evidence_semantic_chunk",
    ):
        op.create_foreign_key(
            "fk_knowledge_evidence_semantic_chunk",
            "knowledge_evidence",
            "semantic_chunk",
            ["semantic_chunk_id"],
            ["id"],
        )


def downgrade() -> None:
    """当前 0002 真源已包含语义块，降到 0002 时保持 schema 不变。"""
