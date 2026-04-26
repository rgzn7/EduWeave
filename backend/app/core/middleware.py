"""
@Date: 2026-04-14
@Author: xisy
@Discription: 请求链路中间件与上下文管理
"""

import time
import uuid
from contextvars import ContextVar, Token

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def set_request_id(request_id: str) -> Token:
    """写入 request_id 上下文。"""
    return _request_id_var.set(request_id)


def get_request_id() -> str:
    """获取当前 request_id。"""
    return _request_id_var.get()


def reset_request_id(token: Token) -> None:
    """重置 request_id 上下文。"""
    _request_id_var.reset(token)


def set_user_id(user_id: str | int) -> Token:
    """写入 user_id 上下文。"""
    return _user_id_var.set(str(user_id))


def get_user_id() -> str:
    """获取当前 user_id。"""
    return _user_id_var.get()


def reset_user_id(token: Token) -> None:
    """重置 user_id 上下文。"""
    _user_id_var.reset(token)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """生成并透传 request_id。"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.user_id = ""
        request_token = set_request_id(request_id)
        user_token = set_user_id("")
        try:
            response = await call_next(request)
        finally:
            reset_user_id(user_token)
            reset_request_id(request_token)
        response.headers["X-Request-Id"] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """记录访问日志。"""

    async def dispatch(self, request: Request, call_next):
        from app.core.logging import get_logger

        logger = get_logger("http.access")
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "请求处理完成",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=getattr(request.state, "request_id", ""),
            user_id=getattr(request.state, "user_id", ""),
        )
        return response
