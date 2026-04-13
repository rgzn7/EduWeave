"""
@Date: 2026-04-11
@Author: xisy
@Discription: 统一响应模型与响应工厂
"""

from typing import Any, Generic, TypeVar

from pydantic import Field

from app.core.middleware import get_request_id
from app.schemas.base import BaseSchema
from app.shared.utils.datetime_util import DateTimeUtil

T = TypeVar("T")


class ErrorDetail(BaseSchema):
    """统一错误明细模型。"""

    code: str = Field(description="错误码", examples=["INVALID_CREDENTIALS"])
    message: str = Field(description="错误描述", examples=["用户名或密码错误"])
    details: dict[str, Any] | None = Field(default=None, description="补充信息")
    field: str | None = Field(default=None, description="字段名")


class PaginationMeta(BaseSchema):
    """分页信息模型。"""

    total_count: int = Field(description="总记录数", examples=[125])
    page: int = Field(description="当前页码", examples=[1])
    page_size: int = Field(description="每页大小", examples=[20])
    total_pages: int = Field(description="总页数", examples=[7])
    has_previous: bool = Field(description="是否存在上一页", examples=[False])
    has_next: bool = Field(description="是否存在下一页", examples=[True])


class PaginatedData(BaseSchema, Generic[T]):
    """分页数据模型。"""

    items: list[T] = Field(description="分页数据列表")
    pagination: PaginationMeta = Field(description="分页元数据")


class ApiResponse(BaseSchema, Generic[T]):
    """统一响应壳模型。"""

    success: bool = Field(description="请求是否成功", examples=[True])
    code: int = Field(description="业务响应状态码", examples=[200])
    message: str = Field(description="响应消息", examples=["操作成功"])
    data: T | None = Field(default=None, description="业务数据")
    timestamp: str = Field(description="响应时间，UTC ISO8601 格式", examples=["2026-04-11T10:00:00.000000Z"])
    request_id: str = Field(description="请求追踪 ID", examples=["a5c0f6b6-1234-5678-9abc-def012345678"])
    errors: list[ErrorDetail] | None = Field(default=None, description="错误明细列表")


class ResponseFactory:
    """统一响应构造工厂。"""

    @staticmethod
    def build(
        *,
        success: bool,
        status_code: int,
        message: str,
        data: Any = None,
        errors: list[ErrorDetail] | None = None,
    ) -> dict[str, Any]:
        """构造统一响应体。"""
        return ApiResponse[Any](
            success=success,
            code=status_code,
            message=message,
            data=data,
            timestamp=DateTimeUtil.to_isoformat(DateTimeUtil.now_utc()),
            request_id=get_request_id(),
            errors=errors or None,
        ).model_dump(mode="json")

    @staticmethod
    def success(data: Any, message: str = "操作成功", status_code: int = 200) -> dict[str, Any]:
        return ApiResponse[Any](
            success=True,
            code=status_code,
            message=message,
            data=data,
            timestamp=DateTimeUtil.to_isoformat(DateTimeUtil.now_utc()),
            request_id=get_request_id(),
        ).model_dump(mode="json")

    @staticmethod
    def paginated(
        items: list[Any],
        total_count: int,
        page: int,
        page_size: int,
        message: str = "获取列表成功",
        status_code: int = 200,
    ) -> dict[str, Any]:
        total_pages = max((total_count + page_size - 1) // page_size, 1)
        payload = PaginatedData[Any](
            items=items,
            pagination=PaginationMeta(
                total_count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_previous=page > 1,
                has_next=page < total_pages,
            ),
        )
        return ApiResponse[PaginatedData[Any]](
            success=True,
            code=status_code,
            message=message,
            data=payload,
            timestamp=DateTimeUtil.to_isoformat(DateTimeUtil.now_utc()),
            request_id=get_request_id(),
        ).model_dump(mode="json")

    @staticmethod
    def error(
        status_code: int,
        message: str,
        errors: list[ErrorDetail] | None = None,
        data: Any = None,
    ) -> dict[str, Any]:
        return ResponseFactory.build(
            success=False,
            status_code=status_code,
            message=message,
            data=data,
            errors=errors or [],
        )

    @staticmethod
    def validation_error(errors: list[dict[str, Any]]) -> dict[str, Any]:
        error_models = [ErrorDetail(**error) for error in errors]
        return ResponseFactory.error(
            status_code=422,
            message="请求参数验证失败",
            errors=error_models,
        )
