"""
@Date: 2026-04-14
@Author: xisy
@Discription: 文件访问模块请求与响应模型
"""

from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class FileDownloadUrlResponse(BaseSchema):
    """文件下载地址响应。"""

    file_object_id: int = Field(description="文件对象主键", examples=[1])
    bucket_name: str = Field(description="存储桶名称", examples=["eduweave-bucket"])
    object_key: str = Field(description="对象路径", examples=["projects/1/parsing/textbook_1/version_1/full.md"])
    signed_url: str = Field(description="签名下载地址")
    expires_in_seconds: int = Field(description="有效期秒数", examples=[3600])
    generated_at: datetime = Field(description="生成时间")
