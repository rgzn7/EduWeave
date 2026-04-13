"""
@Date: 2026-04-13
@Author: xisy
@Discription: 数据库结构对齐校验工具
"""

from collections.abc import Iterable

from sqlalchemy import Engine, inspect, text

from app.core.database import Base
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules import p0_models  # noqa: F401

IGNORED_TABLES = {"alembic_version"}


def collect_schema_diffs(engine: Engine) -> list[str]:
    """收集数据库与当前 metadata 的结构级差异。"""
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - IGNORED_TABLES
    expected_tables = {table.name: table for table in Base.metadata.tables.values()}
    expected_table_names = set(expected_tables)

    diffs: list[str] = []

    for table_name in sorted(expected_table_names - actual_tables):
        diffs.append(f"缺少表：{table_name}")
    for table_name in sorted(actual_tables - expected_table_names):
        diffs.append(f"存在未受支持的额外表：{table_name}")

    for table_name in sorted(expected_table_names & actual_tables):
        expected_table = expected_tables[table_name]
        actual_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        expected_columns = {column.name: column for column in expected_table.columns}

        for column_name in sorted(expected_columns.keys() - actual_columns.keys()):
            diffs.append(f"表 {table_name} 缺少列：{column_name}")
        for column_name in sorted(actual_columns.keys() - expected_columns.keys()):
            diffs.append(f"表 {table_name} 存在额外列：{column_name}")

        shared_columns = expected_columns.keys() & actual_columns.keys()
        for column_name in sorted(shared_columns):
            if bool(expected_columns[column_name].nullable) != bool(actual_columns[column_name]["nullable"]):
                diffs.append(
                    f"表 {table_name} 列 {column_name} 可空性不一致：数据库={actual_columns[column_name]['nullable']}，"
                    f"metadata={expected_columns[column_name].nullable}"
                )

    return diffs


def get_alembic_version(engine: Engine) -> str | None:
    """读取当前数据库的 Alembic 版本。"""
    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return None
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        return row[0] if row else None


def format_schema_diffs(diffs: Iterable[str]) -> str:
    """格式化差异信息，便于脚本输出。"""
    return "\n".join(f"- {diff}" for diff in diffs)
