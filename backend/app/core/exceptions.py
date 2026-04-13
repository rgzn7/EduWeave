"""
@Date: 2026-04-11
@Author: xisy
@Discription: 统一业务异常与异常处理注册
"""

from enum import Enum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.schemas.response import ErrorDetail, ResponseFactory

logger = get_logger(__name__)


class BusinessErrorCode(str, Enum):
    """本阶段业务错误码定义。"""

    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    SYSTEM_CONFIG_INVALID = "SYSTEM_CONFIG_INVALID"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    DEPENDENCY_NOT_READY = "DEPENDENCY_NOT_READY"


ERROR_CODE_HTTP_MAPPING: dict[BusinessErrorCode, int] = {
    BusinessErrorCode.UNAUTHORIZED: 401,
    BusinessErrorCode.INVALID_TOKEN: 401,
    BusinessErrorCode.TOKEN_EXPIRED: 401,
    BusinessErrorCode.INVALID_CREDENTIALS: 401,
    BusinessErrorCode.ACCOUNT_DISABLED: 403,
    BusinessErrorCode.SYSTEM_CONFIG_INVALID: 500,
    BusinessErrorCode.EXTERNAL_SERVICE_ERROR: 503,
    BusinessErrorCode.DEPENDENCY_NOT_READY: 503,
}


class AppException(Exception):
    """统一业务异常对象。"""

    def __init__(
        self,
        code: BusinessErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    @property
    def status_code(self) -> int:
        return ERROR_CODE_HTTP_MAPPING.get(self.code, 500)


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    """业务异常处理器。"""
    error = ErrorDetail(code=exc.code.value, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=ResponseFactory.error(exc.status_code, exc.message, [error]),
    )


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数验证异常处理器。"""
    errors = []
    for error in exc.errors():
        locations = [str(item) for item in error["loc"] if item != "body"]
        errors.append(
            {
                "field": ".".join(locations) if locations else None,
                "message": error["msg"],
                "code": "VALIDATION_ERROR",
                "details": {"type": error["type"]},
            }
        )

    return JSONResponse(status_code=422, content=ResponseFactory.validation_error(errors))


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器。"""
    logger.exception("未处理异常", error=str(exc))
    error = ErrorDetail(code="INTERNAL_SERVER_ERROR", message="服务内部异常", details=None)
    return JSONResponse(
        status_code=500,
        content=ResponseFactory.error(500, "服务内部异常", [error]),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册异常处理器。"""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

