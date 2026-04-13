"""
@Date: 2026-04-11
@Author: xisy
@Discription: 通用 Schema 基类定义
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, field_serializer


class BaseSchema(BaseModel):
    """统一的对外 Schema 基类。"""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", mode="wrap", when_used="json", check_fields=False)
    def serialize_datetime_fields(
        self,
        value: Any,
        handler: SerializerFunctionWrapHandler,
    ) -> Any:
        """统一序列化 datetime 字段，避免重复声明编码器。"""
        if isinstance(value, datetime):
            if value.tzinfo:
                return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return handler(value)
