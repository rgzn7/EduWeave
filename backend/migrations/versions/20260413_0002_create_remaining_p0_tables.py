"""
@Date: 2026-04-30
@Author: xisy
@Discription: 基于 28 表 SQL 真源创建剩余 P0 表
"""

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260413_0002"
down_revision = "20260411_0001"
branch_labels = None
depends_on = None

SCHEMA_SQL_PATH = Path(__file__).resolve().parents[3] / "sql" / "20260430_eduweave_mysql_28_tables.sql"


def _load_upgrade_statements() -> list[str]:
    """从 28 表 SQL 中提取除 sys_user 外的升级语句。"""
    raw_script = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    filtered_lines: list[str] = []
    skip_database_block = False

    for line in raw_script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if stripped.startswith("CREATE DATABASE IF NOT EXISTS"):
            skip_database_block = True
            continue
        if skip_database_block:
            if stripped.endswith(";"):
                skip_database_block = False
            continue
        if stripped.startswith("USE "):
            continue
        if stripped.startswith("DROP TABLE IF EXISTS"):
            continue
        if stripped.startswith("SET "):
            continue
        filtered_lines.append(line)

    statements = [statement.strip() for statement in "\n".join(filtered_lines).split(";") if statement.strip()]
    upgrade_statements: list[str] = []
    for statement in statements:
        normalized_statement = statement.lower()
        if normalized_statement.startswith("create table `sys_user`"):
            continue
        if normalized_statement.startswith("create table "):
            upgrade_statements.append(statement)
            continue
        if normalized_statement.startswith("alter table `project`"):
            upgrade_statements.append(statement)
    return upgrade_statements


def upgrade() -> None:
    for statement in _load_upgrade_statements():
        op.execute(statement)


def downgrade() -> None:
    op.drop_constraint("fk_project_latest_generation_batch", "project", type_="foreignkey")
    op.drop_constraint("fk_project_current_profile_version", "project", type_="foreignkey")
    op.drop_constraint("fk_project_current_textbook_version", "project", type_="foreignkey")

    tables = [
        "audit_log",
        "generation_trace",
        "task_step_record",
        "task_record",
        "coverage_report",
        "question_item",
        "paper_result",
        "courseware_result",
        "generation_batch",
        "assessment_blueprint",
        "lesson_plan",
        "curriculum_plan",
        "knowledge_evidence",
        "knowledge_point",
        "semantic_chunk",
        "chapter_node",
        "knowledge_version",
        "parse_issue",
        "parse_block",
        "parse_page",
        "parse_version",
        "learner_profile_record",
        "learner_profile_version",
        "learner_profile_file",
        "textbook_version",
        "file_object",
        "project",
    ]
    for table_name in tables:
        op.drop_table(table_name)
