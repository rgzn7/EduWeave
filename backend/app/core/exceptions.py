"""
@Date: 2026-05-03
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
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_REFERENCE_INVALID = "PROJECT_REFERENCE_INVALID"
    TEXTBOOK_NOT_FOUND = "TEXTBOOK_NOT_FOUND"
    LEARNER_PROFILE_NOT_FOUND = "LEARNER_PROFILE_NOT_FOUND"
    PARSE_VERSION_NOT_FOUND = "PARSE_VERSION_NOT_FOUND"
    PARSE_VERSION_NOT_CONFIRMED = "PARSE_VERSION_NOT_CONFIRMED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    KNOWLEDGE_VERSION_NOT_FOUND = "KNOWLEDGE_VERSION_NOT_FOUND"
    GENERATION_BATCH_NOT_FOUND = "GENERATION_BATCH_NOT_FOUND"
    CURRICULUM_PLAN_NOT_FOUND = "CURRICULUM_PLAN_NOT_FOUND"
    LESSON_PLAN_NOT_FOUND = "LESSON_PLAN_NOT_FOUND"
    ASSESSMENT_BLUEPRINT_NOT_FOUND = "ASSESSMENT_BLUEPRINT_NOT_FOUND"
    PAPER_RESULT_NOT_FOUND = "PAPER_RESULT_NOT_FOUND"
    COURSEWARE_RESULT_NOT_FOUND = "COURSEWARE_RESULT_NOT_FOUND"
    GENERATION_BASELINE_INVALID = "GENERATION_BASELINE_INVALID"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
    TASK_CONFLICT = "TASK_CONFLICT"
    RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"
    INVALID_PARSE_STRATEGY = "INVALID_PARSE_STRATEGY"
    INVALID_PAGE_RANGE = "INVALID_PAGE_RANGE"
    KNOWLEDGE_REVISION_INVALID = "KNOWLEDGE_REVISION_INVALID"
    LLM_REQUEST_FAILED = "LLM_REQUEST_FAILED"
    LLM_RESULT_INVALID = "LLM_RESULT_INVALID"
    MINERU_SUBMIT_FAILED = "MINERU_SUBMIT_FAILED"
    MINERU_POLL_TIMEOUT = "MINERU_POLL_TIMEOUT"
    MINERU_TASK_FAILED = "MINERU_TASK_FAILED"
    MINERU_RESULT_INVALID = "MINERU_RESULT_INVALID"
    RACCOON_REQUEST_FAILED = "RACCOON_REQUEST_FAILED"
    RACCOON_POLL_TIMEOUT = "RACCOON_POLL_TIMEOUT"
    RACCOON_RESULT_INVALID = "RACCOON_RESULT_INVALID"


ERROR_CODE_HTTP_MAPPING: dict[BusinessErrorCode, int] = {
    BusinessErrorCode.UNAUTHORIZED: 401,
    BusinessErrorCode.INVALID_TOKEN: 401,
    BusinessErrorCode.TOKEN_EXPIRED: 401,
    BusinessErrorCode.INVALID_CREDENTIALS: 401,
    BusinessErrorCode.ACCOUNT_DISABLED: 403,
    BusinessErrorCode.SYSTEM_CONFIG_INVALID: 500,
    BusinessErrorCode.EXTERNAL_SERVICE_ERROR: 503,
    BusinessErrorCode.DEPENDENCY_NOT_READY: 503,
    BusinessErrorCode.PROJECT_NOT_FOUND: 404,
    BusinessErrorCode.PROJECT_REFERENCE_INVALID: 422,
    BusinessErrorCode.TEXTBOOK_NOT_FOUND: 404,
    BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND: 404,
    BusinessErrorCode.PARSE_VERSION_NOT_FOUND: 404,
    BusinessErrorCode.PARSE_VERSION_NOT_CONFIRMED: 422,
    BusinessErrorCode.TASK_NOT_FOUND: 404,
    BusinessErrorCode.FILE_NOT_FOUND: 404,
    BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND: 404,
    BusinessErrorCode.GENERATION_BATCH_NOT_FOUND: 404,
    BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND: 404,
    BusinessErrorCode.LESSON_PLAN_NOT_FOUND: 404,
    BusinessErrorCode.ASSESSMENT_BLUEPRINT_NOT_FOUND: 404,
    BusinessErrorCode.PAPER_RESULT_NOT_FOUND: 404,
    BusinessErrorCode.COURSEWARE_RESULT_NOT_FOUND: 404,
    BusinessErrorCode.GENERATION_BASELINE_INVALID: 422,
    BusinessErrorCode.INVALID_FILE_TYPE: 422,
    BusinessErrorCode.FILE_UPLOAD_FAILED: 503,
    BusinessErrorCode.TASK_CONFLICT: 409,
    BusinessErrorCode.RESOURCE_FORBIDDEN: 403,
    BusinessErrorCode.INVALID_PARSE_STRATEGY: 422,
    BusinessErrorCode.INVALID_PAGE_RANGE: 422,
    BusinessErrorCode.KNOWLEDGE_REVISION_INVALID: 422,
    BusinessErrorCode.LLM_REQUEST_FAILED: 503,
    BusinessErrorCode.LLM_RESULT_INVALID: 503,
    BusinessErrorCode.MINERU_SUBMIT_FAILED: 503,
    BusinessErrorCode.MINERU_POLL_TIMEOUT: 504,
    BusinessErrorCode.MINERU_TASK_FAILED: 503,
    BusinessErrorCode.MINERU_RESULT_INVALID: 503,
    BusinessErrorCode.RACCOON_REQUEST_FAILED: 503,
    BusinessErrorCode.RACCOON_POLL_TIMEOUT: 504,
    BusinessErrorCode.RACCOON_RESULT_INVALID: 503,
}


class AppException(Exception):
    """统一业务异常对象。"""

    def __init__(
        self,
        code: BusinessErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.data = data

    @property
    def status_code(self) -> int:
        return ERROR_CODE_HTTP_MAPPING.get(self.code, 500)


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    """业务异常处理器。"""
    error = ErrorDetail(code=exc.code.value, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=ResponseFactory.error(exc.status_code, exc.message, [error], data=exc.data),
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
