"""
@Date: 2026-04-14
@Author: xisy
@Discription: 解析模块请求与响应模型
"""

from datetime import datetime

from pydantic import Field, field_validator

from app.core.constants import MINERU_STRATEGY_VLM_DEFAULT
from app.schemas.base import BaseSchema


class ParseTaskCreateRequest(BaseSchema):
    """解析任务创建请求。"""

    strategy_code: str = Field(
        default=MINERU_STRATEGY_VLM_DEFAULT,
        description="解析策略编码",
        min_length=1,
        max_length=64,
        examples=[MINERU_STRATEGY_VLM_DEFAULT],
    )
    set_as_current_on_success: bool = Field(
        default=False,
        description="是否在成功后设为当前可用解析版本",
        examples=[True],
    )


class ParseReparseTaskCreateRequest(BaseSchema):
    """页级重解析任务创建请求。"""

    page_range_text: str = Field(description="页码范围文本", min_length=1, max_length=255, examples=["2-3,5"])
    strategy_code: str = Field(
        default=MINERU_STRATEGY_VLM_DEFAULT,
        description="解析策略编码",
        min_length=1,
        max_length=64,
        examples=[MINERU_STRATEGY_VLM_DEFAULT],
    )
    set_as_current_on_success: bool = Field(
        default=False,
        description="是否在成功后设为当前可用解析版本",
        examples=[True],
    )

    @field_validator("page_range_text")
    @classmethod
    def validate_page_range_text(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("page_range_text 不能为空")
        return normalized_value


class ParseManualRevisionBlockRequest(BaseSchema):
    """解析块人工修正请求。"""

    block_no: int = Field(description="块序号", ge=1, examples=[1])
    block_type: str = Field(description="块类型", min_length=1, max_length=32, examples=["paragraph"])
    heading_level: int | None = Field(default=None, description="标题级别", ge=1, le=6, examples=[2])
    bbox_json: dict | None = Field(
        default=None,
        description="坐标框",
        examples=[{"x0": 12.5, "y0": 18.0, "x1": 180.0, "y1": 56.0}],
    )
    text_content: str | None = Field(default=None, description="文本内容", examples=["人工修正后的块文本"])
    markdown_content: str | None = Field(default=None, description="Markdown 内容", examples=["人工修正后的块文本"])
    asset_file_id: int | None = Field(default=None, description="关联资源文件主键", examples=[1])
    origin_ref_json: dict | None = Field(
        default=None,
        description="原始来源引用",
        examples=[{"source": "manual", "operator": "teacher_demo"}],
    )
    is_deleted: bool = Field(default=False, description="是否逻辑删除", examples=[False])


class ParseManualRevisionPageRequest(BaseSchema):
    """解析页人工修正请求。"""

    page_no: int = Field(description="页码", ge=1, examples=[1])
    page_status: str = Field(default="success", description="页状态", min_length=1, max_length=32, examples=["success"])
    text_content: str | None = Field(default=None, description="页文本内容", examples=["人工修正后的页文本"])
    markdown_content: str | None = Field(default=None, description="页 Markdown 内容", examples=["人工修正后的页文本"])
    layout_json: dict | None = Field(
        default=None,
        description="页布局 JSON",
        examples=[[{"type": "paragraph", "bbox": [12.5, 18.0, 180.0, 56.0]}]],
    )
    blocks: list[ParseManualRevisionBlockRequest] = Field(
        description="块列表",
        min_length=1,
        examples=[
            [
                {
                    "block_no": 1,
                    "block_type": "paragraph",
                    "text_content": "人工修正后的块文本",
                    "markdown_content": "人工修正后的块文本",
                    "origin_ref_json": {"source": "manual"},
                    "is_deleted": False,
                }
            ]
        ],
    )


class ParseManualRevisionRequest(BaseSchema):
    """解析版本人工修正请求。"""

    pages: list[ParseManualRevisionPageRequest] = Field(
        description="需要替换的页列表",
        min_length=1,
        examples=[
            [
                {
                    "page_no": 1,
                    "page_status": "success",
                    "text_content": "人工修正后的页文本",
                    "markdown_content": "人工修正后的页文本",
                    "layout_json": [{"type": "paragraph", "bbox": [12.5, 18.0, 180.0, 56.0]}],
                    "blocks": [
                        {
                            "block_no": 1,
                            "block_type": "paragraph",
                            "text_content": "人工修正后的块文本",
                            "markdown_content": "人工修正后的块文本",
                            "origin_ref_json": {"source": "manual"},
                            "is_deleted": False,
                        }
                    ],
                }
            ]
        ],
    )
    set_as_current_on_success: bool = Field(
        default=False,
        description="是否在成功后设为当前可用解析版本",
        examples=[True],
    )


class ParseBlockResponse(BaseSchema):
    """解析块响应。"""

    id: int = Field(description="解析块主键", examples=[1])
    parse_version_id: int = Field(description="解析版本主键", examples=[1])
    parse_page_id: int = Field(description="解析页主键", examples=[1])
    block_no: int = Field(description="块序号", examples=[1])
    block_type: str = Field(description="块类型", examples=["paragraph"])
    heading_level: int | None = Field(default=None, description="标题级别")
    bbox_json: dict | None = Field(default=None, description="坐标框")
    text_content: str | None = Field(default=None, description="文本内容")
    markdown_content: str | None = Field(default=None, description="Markdown 内容")
    asset_file_id: int | None = Field(default=None, description="资源文件主键")
    origin_ref_json: dict | None = Field(default=None, description="来源引用")
    is_deleted: bool = Field(description="是否删除", examples=[False])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ParsePageResponse(BaseSchema):
    """解析页响应。"""

    id: int = Field(description="解析页主键", examples=[1])
    parse_version_id: int = Field(description="解析版本主键", examples=[1])
    page_no: int = Field(description="页码", examples=[1])
    source_page_image_file_id: int | None = Field(default=None, description="页图文件主键")
    page_status: str = Field(description="页状态", examples=["success"])
    has_issue: bool = Field(description="是否存在异常", examples=[False])
    text_content: str | None = Field(default=None, description="页文本内容")
    markdown_content: str | None = Field(default=None, description="页 Markdown 内容")
    layout_json: dict | None = Field(default=None, description="布局数据")
    blocks: list[ParseBlockResponse] = Field(description="块列表")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ParseIssueResponse(BaseSchema):
    """解析异常响应。"""

    id: int = Field(description="解析异常主键", examples=[1])
    parse_version_id: int = Field(description="解析版本主键", examples=[1])
    parse_page_id: int | None = Field(default=None, description="解析页主键")
    parse_block_id: int | None = Field(default=None, description="解析块主键")
    related_reparse_version_id: int | None = Field(default=None, description="关联重解析版本主键")
    issue_type: str = Field(description="异常类型", examples=["empty_page"])
    severity: str = Field(description="严重级别", examples=["medium"])
    issue_status: str = Field(description="异常状态", examples=["open"])
    detected_by: str = Field(description="发现来源", examples=["system"])
    description: str | None = Field(default=None, description="异常描述")
    resolution_note: str | None = Field(default=None, description="处理说明")
    created_by: int | None = Field(default=None, description="创建人")
    resolved_by: int | None = Field(default=None, description="处理人")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ParseVersionListItemResponse(BaseSchema):
    """解析版本列表项响应。"""

    id: int = Field(description="解析版本主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    textbook_version_id: int = Field(description="教材版本主键", examples=[1])
    parent_parse_version_id: int | None = Field(default=None, description="父解析版本主键")
    version_no: int = Field(description="版本号", examples=[1])
    parse_mode: str = Field(description="解析模式", examples=["full"])
    page_range_text: str | None = Field(default=None, description="页范围文本")
    strategy_code: str = Field(description="解析策略编码", examples=[MINERU_STRATEGY_VLM_DEFAULT])
    mineru_model: str | None = Field(default=None, description="MinerU 模型名称")
    parse_status: str = Field(description="解析状态", examples=["success"])
    review_status: str = Field(description="审核状态", examples=["pending"])
    version_status: str = Field(description="版本状态", examples=["ready"])
    page_count: int | None = Field(default=None, description="页数")
    issue_count: int = Field(description="异常数量", examples=[1])
    source_markdown_file_id: int | None = Field(default=None, description="解析 Markdown 文件主键")
    source_json_file_id: int | None = Field(default=None, description="解析 JSON 文件主键")
    asset_manifest_json: dict | None = Field(default=None, description="资源清单")
    diff_json: dict | None = Field(default=None, description="差异摘要")
    error_summary: str | None = Field(default=None, description="错误摘要")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ParseVersionDetailResponse(ParseVersionListItemResponse):
    """解析版本详情响应。"""
