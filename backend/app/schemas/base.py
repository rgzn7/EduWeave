"""
@Date: 2026-04-11
@Author: xisy
@Discription: 通用 Schema 基类定义
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """统一的对外 Schema 基类。"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            datetime: lambda value: (
                value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                if value.tzinfo
                else value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            )
        },
    )

