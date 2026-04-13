"""
@Date: 2026-04-13
@Author: xisy
@Discription: 教材模块请求与响应模型
"""

from datetime import datetime
from typing import Annotated

from fastapi import Form
from pydantic import Field

from app.schemas.base import BaseSchema


class TextbookUploadRequest(BaseSchema):
    """教材上传请求。"""

    textbook_name: str | None = Field(default=None, description="教材名称", examples=["人民教育出版社三年级上册数学"])
    publisher: str | None = Field(default=None, description="出版社", examples=["人民教育出版社"])
    subject_code: str | None = Field(default=None, description="学科编码", examples=["math"])
    grade_code: str | None = Field(default=None, description="年级编码", examples=["grade_3"])
    volume_code: str | None = Field(default=None, description="册别", examples=["上册"])
    edition_label: str | None = Field(default=None, description="版本标签", examples=["2024秋季版"])
    isbn: str | None = Field(default=None, description="ISBN", examples=["9787101234567"])
    remark: str | None = Field(default=None, description="备注", examples=["教师备课主教材"])
    set_as_current: bool = Field(default=False, description="是否设为当前版本", examples=[True])

    @classmethod
    def as_form(
        cls,
        textbook_name: Annotated[str | None, Form(description="教材名称", examples=["人民教育出版社三年级上册数学"])] = None,
        publisher: Annotated[str | None, Form(description="出版社", examples=["人民教育出版社"])] = None,
        subject_code: Annotated[str | None, Form(description="学科编码", examples=["math"])] = None,
        grade_code: Annotated[str | None, Form(description="年级编码", examples=["grade_3"])] = None,
        volume_code: Annotated[str | None, Form(description="册别", examples=["上册"])] = None,
        edition_label: Annotated[str | None, Form(description="版本标签", examples=["2024秋季版"])] = None,
        isbn: Annotated[str | None, Form(description="ISBN", examples=["9787101234567"])] = None,
        remark: Annotated[str | None, Form(description="备注", examples=["教师备课主教材"])] = None,
        set_as_current: Annotated[bool, Form(description="是否设为当前版本", examples=[True])] = False,
    ) -> "TextbookUploadRequest":
        """将 multipart/form-data 字段转换为教材上传请求模型。"""
        return cls(
            textbook_name=textbook_name,
            publisher=publisher,
            subject_code=subject_code,
            grade_code=grade_code,
            volume_code=volume_code,
            edition_label=edition_label,
            isbn=isbn,
            remark=remark,
            set_as_current=set_as_current,
        )


class FileObjectSummaryResponse(BaseSchema):
    """文件对象摘要响应。"""

    id: int = Field(description="文件对象主键", examples=[1])
    bucket_name: str = Field(description="存储桶名称", examples=["eduweave-demo"])
    object_key: str = Field(description="对象路径", examples=["projects/1/textbooks/1/source.pdf"])
    original_filename: str = Field(description="原始文件名", examples=["教材.pdf"])
    file_ext: str | None = Field(default=None, description="扩展名", examples=[".pdf"])
    mime_type: str | None = Field(default=None, description="MIME 类型", examples=["application/pdf"])
    file_size: int = Field(description="文件大小", examples=[1024])
    content_hash: str = Field(description="文件哈希", examples=["abcdef123456"])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class TextbookVersionListItemResponse(BaseSchema):
    """教材版本列表项响应。"""

    id: int = Field(description="教材版本主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    version_no: int = Field(description="项目内版本号", examples=[1])
    textbook_name: str = Field(description="教材名称", examples=["人民教育出版社三年级上册数学"])
    publisher: str | None = Field(default=None, description="出版社")
    subject_code: str = Field(description="学科编码", examples=["math"])
    grade_code: str = Field(description="年级编码", examples=["grade_3"])
    volume_code: str | None = Field(default=None, description="册别")
    edition_label: str | None = Field(default=None, description="版本标签")
    isbn: str | None = Field(default=None, description="ISBN")
    page_count: int | None = Field(default=None, description="页数")
    parse_status: str = Field(description="解析状态", examples=["pending"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    remark: str | None = Field(default=None, description="备注")
    is_current: bool = Field(description="是否为当前项目引用的教材版本", examples=[True])
    source_file: FileObjectSummaryResponse = Field(description="源文件摘要")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class TextbookVersionDetailResponse(TextbookVersionListItemResponse):
    """教材版本详情响应。"""

    auto_identify_json: dict | None = Field(default=None, description="自动识别结果")
