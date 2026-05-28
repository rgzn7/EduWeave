"""
@Date: 2026-05-28
@Author: xisy
@Discription: Alembic 迁移测试
"""

from pathlib import Path

import pymysql
import pytest
from alembic import command
from alembic.config import Config

from app.core.config import get_settings


def test_alembic_upgrade_head() -> None:
    """Alembic 应可成功升级到最新版本并创建完整 P0 schema。"""
    settings = get_settings()
    database_name = "eduweave_alembic_test"

    try:
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database="mysql",
            charset="utf8mb4",
            autocommit=True,
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MySQL 不可用，跳过 Alembic 集成测试：{exc}")

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            (
                f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
                f"@{settings.mysql_host}:{settings.mysql_port}/{database_name}?charset=utf8mb4"
            ),
        )
        command.upgrade(config, "head")

        with connection.cursor() as cursor:
            cursor.execute(f"USE `{database_name}`")
            cursor.execute("SHOW TABLES")
            table_names = {row[0] for row in cursor.fetchall()}
            assert "sys_user" in table_names
            assert "project" in table_names
            assert "generation_batch" in table_names
            assert "audit_log" in table_names
            assert "semantic_chunk" in table_names
            assert "homework_blueprint" in table_names
            assert "homework_result" in table_names
            assert "homework_question" in table_names
            assert "generation_run" in table_names
            assert "lesson_plan_generation_item" in table_names
            assert "alembic_version" in table_names
            assert len(table_names) == 34
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        connection.close()
