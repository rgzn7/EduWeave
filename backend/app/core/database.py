"""
@Date: 2026-04-11
@Author: xisy
@Discription: 数据库连接、会话与健康检查
"""

import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """SQLAlchemy 模型基类。"""


def create_sqlalchemy_engine() -> Engine:
    """创建 SQLAlchemy 引擎。"""
    return create_engine(
        settings.sqlalchemy_database_uri,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )


engine = create_sqlalchemy_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def get_db_session() -> Generator[Session, None, None]:
    """提供数据库会话依赖。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_mysql_health() -> dict[str, str | float]:
    """执行 MySQL 健康检查。"""
    started_at = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "detail": "MySQL 连接正常",
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    except SQLAlchemyError as exc:
        return {
            "status": "error",
            "detail": f"MySQL 连接失败：{exc}",
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }

