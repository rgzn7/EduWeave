"""
@Date: 2026-04-11
@Author: xisy
@Discription: 结构化日志配置
"""

import logging
import sys
from typing import Any

import structlog

from app.core.middleware import get_request_id, get_user_id

_LOGGING_CONFIGURED = False


def add_runtime_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """向日志上下文注入 request_id 与 user_id。"""
    request_id = get_request_id()
    user_id = get_user_id()
    if request_id:
        event_dict["request_id"] = request_id
    if user_id:
        event_dict["user_id"] = user_id
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """初始化 structlog 配置。"""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            add_runtime_context,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> Any:
    """获取结构化日志对象。"""
    return structlog.get_logger(name)

