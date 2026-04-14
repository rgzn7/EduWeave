"""
@Date: 2026-04-14
@Author: xisy
@Discription: MinerU 适配层内部数据模型
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MineruBatchFileResult:
    """MinerU 批量任务中的单文件结果。"""

    file_name: str
    state: str
    full_zip_url: str | None
    err_msg: str | None
    data_id: str | None
    extract_progress: dict[str, Any] | None = None


@dataclass(slots=True)
class MineruUploadBatchResult:
    """MinerU 上传链接申请结果。"""

    batch_id: str
    file_urls: list[str]
    trace_id: str | None = None


@dataclass(slots=True)
class NormalizedBlock:
    """归一化后的结构块。"""

    page_no: int
    block_no: int
    block_type: str
    text_content: str | None
    markdown_content: str | None
    heading_level: int | None = None
    bbox_json: dict[str, Any] | None = None
    asset_relative_path: str | None = None
    origin_ref_json: dict[str, Any] | None = None


@dataclass(slots=True)
class NormalizedPage:
    """归一化后的页结果。"""

    page_no: int
    text_content: str | None
    markdown_content: str | None
    layout_json: dict[str, Any] | None
    blocks: list[NormalizedBlock] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedDocument:
    """归一化后的文档解析结果。"""

    batch_id: str
    file_name: str
    data_id: str | None
    model_version: str
    markdown_text: str
    content_list_json: list[dict[str, Any]]
    pages: list[NormalizedPage]
    full_zip_bytes: bytes
    asset_files: dict[str, bytes]
    raw_metadata: dict[str, Any]
