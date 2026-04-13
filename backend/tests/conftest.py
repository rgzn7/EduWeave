"""
@Date: 2026-04-11
@Author: xisy
@Discription: 测试环境公共夹具
"""

import os
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote_plus

os.environ.setdefault("APP_NAME", "EduWeave Backend Test")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_HOST", "127.0.0.1")
os.environ.setdefault("APP_PORT", "8001")
os.environ.setdefault("APP_VERSION", "0.1.0-test")
os.environ.setdefault("APP_LOAD_DOTENV", "0")
os.environ.setdefault("API_V1_PREFIX", "/api/v1")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "boss1114")
os.environ.setdefault("MYSQL_DATABASE", "eduweave")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "120")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("OBS_ENDPOINT", "https://obs.test.example.com")
os.environ.setdefault("OBS_AK", "test-ak")
os.environ.setdefault("OBS_SK", "test-sk")
os.environ.setdefault("OBS_BUCKET", "test-bucket")
os.environ.setdefault("OBS_BASE_PREFIX", "projects")
os.environ.setdefault("MILVUS_URI", "http://127.0.0.1:19530")
os.environ.setdefault("MILVUS_TOKEN", "")
os.environ.setdefault("MILVUS_DB_NAME", "default")
os.environ.setdefault("MILVUS_COLLECTION_PREFIX", "eduweave_test")
os.environ.setdefault("MILVUS_EMBEDDING_DIM", "4")
os.environ.setdefault("MILVUS_INDEX_TYPE", "HNSW")
os.environ.setdefault("MILVUS_METRIC_TYPE", "COSINE")

import pytest
import pymysql
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import SysUser

TEST_PASSWORD = "Teacher@123"
SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "20260413_eduweave_mysql_27_tables.sql"


def build_mysql_uri(database_name: str) -> str:
    """构建指定数据库的 SQLAlchemy 连接串。"""
    settings = get_settings()
    return (
        f"mysql+pymysql://{quote_plus(settings.mysql_user)}:{quote_plus(settings.mysql_password)}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{database_name}?charset=utf8mb4"
    )


def execute_schema_sql(database_name: str) -> None:
    """向指定 MySQL 数据库执行 27 张表初始化脚本。"""
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database_name,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
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
            filtered_lines.append(line)

        statements = [statement.strip() for statement in "\n".join(filtered_lines).split(";") if statement.strip()]
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
    finally:
        connection.close()


@pytest.fixture(scope="session")
def mysql_test_database_name() -> Generator[str, None, None]:
    """创建供测试使用的临时 MySQL 数据库。"""
    settings = get_settings()
    database_name = f"eduweave_test_{uuid4().hex[:8]}"
    admin_connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database="mysql",
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with admin_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
            cursor.execute(
                f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        execute_schema_sql(database_name)
        yield database_name
    finally:
        with admin_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        admin_connection.close()


@pytest.fixture()
def mysql_session_factory(mysql_test_database_name):
    """提供 MySQL 会话工厂。"""
    engine = create_engine(
        build_mysql_uri(mysql_test_database_name),
        pool_pre_ping=True,
        future=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def seeded_session_factory(mysql_session_factory):
    """初始化测试教师账号并返回会话工厂。"""
    session = mysql_session_factory()
    try:
        session.execute(text("DELETE FROM sys_user"))
        session.commit()
        session.add_all(
            [
                SysUser(
                    username="teacher_demo",
                    display_name="示例教师",
                    password_hash=hash_password(TEST_PASSWORD),
                    role_code="teacher",
                    status="active",
                ),
                SysUser(
                    username="teacher_disabled",
                    display_name="禁用教师",
                    password_hash=hash_password(TEST_PASSWORD),
                    role_code="teacher",
                    status="disabled",
                ),
            ]
        )
        session.commit()
        yield mysql_session_factory
    finally:
        session.close()


@pytest.fixture()
def client(seeded_session_factory):
    """提供测试客户端并覆写数据库依赖。"""

    def override_get_db_session():
        session = seeded_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
